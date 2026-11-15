/* LED map: every fan as a ring of individually addressable LEDs. Identify, arrange, and paint LED by LED. */
"use strict";

const CELL = 150, RING = 50;

function ledMapView(page) {
  const V = { fixtures: [], paint: {}, sel: null, painting: false, hits: [] };
  const cv = h("canvas", { style: { width: "100%", display: "block", cursor: "pointer", borderRadius: "12px", background: "#05060a" } });
  const side = h("div.card", { style: { padding: "14px" } });
  const toolbar = h("div.row.wrap", { style: { marginBottom: "12px" } });
  const root = h("div", toolbar, h("div.stack", { style: { gap: "12px" } },
    h("div.card", { style: { padding: "12px" } }, cv, h("div.small.muted", { style: { marginTop: "8px" } },
      "Each dot is one LED. Click a fan's centre to select it; in Paint mode click LEDs to colour them with Colour 1.")), side));

  V.load = async () => {
    const m = await App.api.light_map();
    V.fixtures = m.fixtures; V.paint = m.paint || {};
    V.drawToolbar(); V.drawSide();
  };
  V.save = () => { clearTimeout(V.st); V.st = setTimeout(() => App.api.light_map_save(V.fixtures), 300); };
  V.savePaint = () => { clearTimeout(V.pt); V.pt = setTimeout(async () => { await App.api.light_paint_save(V.paint); if (page.o.effect === "Custom paint") page.changed(); }, 250); };

  V.drawToolbar = () => {
    const leds = V.fixtures.reduce((a, f) => a + f.count, 0), fans = V.fixtures.filter(f => f.kind === "fan").length;
    toolbar.replaceChildren(
      h("span.pill.info", `${fans} fans · ${V.fixtures.length} lights · ${leds} individually controlled LEDs`),
      h("div.spacer"),
      h("button.btn.sm" + (V.painting ? ".primary" : ""), { onclick: () => { V.painting = !V.painting; if (V.painting) { page.selectEffect("Custom paint"); toast("Paint mode: click LEDs to colour them with Colour 1"); } V.drawToolbar(); } }, icon("light"), V.painting ? "Painting…" : "Paint LEDs"),
      h("button.btn.sm", { onclick: () => { if (V.sel) { V.paint[V.sel] = Object.fromEntries([...Array(V.fixtures.find(f => f.id === V.sel).count)].map((_, k) => [String(k), page.o.color])); V.savePaint(); } else toast("Select a fan first", true); } }, "Fill selected"),
      h("button.btn.sm.ghost", { onclick: () => { V.paint = {}; V.savePaint(); } }, "Clear paint"));
  };

  V.drawSide = () => {
    const f = V.fixtures.find(x => x.id === V.sel);
    if (!f) {
      side.replaceChildren(h("h3", "Your lights"), h("div.small.muted", { style: { margin: "6px 0 10px" } }, "Pick one to identify it, rename it, or move it so the map matches your case."),
        h("div.stack", { style: { gap: "4px" } }, V.fixtures.map(x => h("div.dev", { style: { gridTemplateColumns: "1fr auto" }, onclick: () => { V.sel = x.id; V.drawSide(); } },
          h("div", h("div.name", x.label), h("div.meta", `${x.device.replace(" (direct)", "")} · ${x.count} LEDs`)), h("span.pill", x.kind)))));
      return;
    }
    const mv = (dx, dy) => { f.x = Math.max(0, f.x + dx); f.y = Math.max(0, f.y + dy); V.save(); };
    side.replaceChildren(
      h("div.row", h("h3", { style: { margin: 0 } }, "Selected"), h("div.spacer"), h("button.btn.sm.ghost", { onclick: () => { V.sel = null; V.drawSide(); } }, "All lights")),
      h("input", { type: "text", value: f.label, style: { width: "100%", margin: "10px 0" }, onchange: e => { f.label = e.target.value; V.save(); } }),
      h("div.small.muted", `${f.device} · ${f.zone} · LEDs ${f.start + 1}-${f.start + f.count}`),
      h("button.btn.primary", { style: { width: "100%", justifyContent: "center", margin: "12px 0" }, onclick: async () => { await App.api.light_identify(f.device, f.zone); toast("Flashing it white for 3 seconds - look in your case"); } }, icon("light"), "Identify (flash white)"),
      h("div.opt", h("div.t", "Shape"), h("select", { onchange: e => { f.kind = e.target.value; V.save(); } }, ["fan", "strip"].map(k => h("option", { selected: f.kind === k }, k)))),
      h("div.nav-label", { style: { padding: "12px 0 6px" } }, "Move on map"),
      h("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 44px)", gap: "6px", justifyContent: "center" } },
        h("span"), h("button.btn.sm", { onclick: () => mv(0, -1) }, "↑"), h("span"),
        h("button.btn.sm", { onclick: () => mv(-1, 0) }, "←"), h("span"), h("button.btn.sm", { onclick: () => mv(1, 0) }, "→"),
        h("span"), h("button.btn.sm", { onclick: () => mv(0, 1) }, "↓"), h("span")),
      h("div.small.muted", { style: { marginTop: "10px" } }, "Sweeps and waves travel left → right across this map, so line it up with how the fans sit in your case."));
  };

  // ---- drawing (called every animation frame by the lighting page)
  V.draw = (t) => {
    if (!V.fixtures.length) { const [ctx, w] = fitCanvas(cv); cv.style.height = "160px"; ctx.fillStyle = css("--muted"); ctx.font = "14px sans-serif"; ctx.fillText("No LEDs mapped yet - set up your fan channels (Devices & setup tab).", 20, 80); return; }
    const maxX = Math.max(5, ...V.fixtures.map(f => f.x + 1)), maxY = Math.max(...V.fixtures.map(f => f.y)) + 1;
    const cell = Math.min(CELL, (cv.getBoundingClientRect().width || 500) / maxX);
    cv.style.height = Math.max(180, maxY * cell) + "px";
    const [ctx, w] = fitCanvas(cv);
    ctx.clearRect(0, 0, w, maxY * cell);
    const o = page.o, c1 = hexToRgb(o.color), c2 = hexToRgb(o.color2);
    const xs = V.fixtures.map(f => f.x), x0 = Math.min(...xs) - 0.5, x1 = Math.max(...xs) + 0.5;
    const ys = V.fixtures.map(f => f.y), y0 = Math.min(...ys) - 0.5, y1 = Math.max(...ys) + 0.5;
    const ledXY = (f, k) => { const a = k / f.count; return f.kind === "fan" ? [f.x + 0.42 * Math.cos(2 * Math.PI * a), f.y + 0.42 * Math.sin(2 * Math.PI * a), a] : [f.x - 0.45 + 0.9 * (k / Math.max(1, f.count - 1)), f.y, a]; };
    const val = { temp: App.snap?.summary.cpu_temp, load: App.snap?.summary.cpu_load };
    V.hits = [];
    V.fixtures.forEach((f, fi) => {
      const cx = (f.x + 0.5) * cell, cy = (f.y + 0.5) * cell - 6, r = Math.min(RING, cell * 0.3);
      const classic = FX[o.effect]
        ? fxFixture(o.effect, f.id, [...Array(f.count)].map((_, k) => { const [lx, ly, a] = ledXY(f, k); return [(lx - x0) / Math.max(1e-6, x1 - x0), (ly - y0) / Math.max(1e-6, y1 - y0), a]; }), fi, V.fixtures.length, t, c1, c2, o.speed, o.intensity, o.palette)
        : SPATIAL.has(o.effect) ? null : effectFrame(o.effect, t, f.count, c1, c2, o.speed, 1, val);
      ctx.strokeStyle = f.id === V.sel ? css("--accent") : "#2a3142"; ctx.lineWidth = f.id === V.sel ? 2 : 1;
      if (f.kind === "fan") { ctx.beginPath(); ctx.arc(cx, cy, r + 14, 0, Math.PI * 2); ctx.stroke(); }
      else ctx.strokeRect(cx - cell * 0.45, cy - 16, cell * 0.9, 32);
      for (let k = 0; k < f.count; k++) {
        const a = k / f.count;
        const px = f.kind === "fan" ? cx + r * Math.cos(2 * Math.PI * a) : cx - cell * 0.4 + cell * 0.8 * (k / Math.max(1, f.count - 1));
        const py = f.kind === "fan" ? cy + r * Math.sin(2 * Math.PI * a) : cy;
        const fx = f.kind === "fan" ? f.x + 0.42 * Math.cos(2 * Math.PI * a) : f.x - 0.45 + 0.9 * (k / Math.max(1, f.count - 1));
        const gx = (fx - x0) / Math.max(1e-6, x1 - x0);
        let col = classic ? classic[k] : spatialColor(o.effect, t, fi, V.fixtures.length, k, f.count, gx, c1, c2, o.speed, (V.paint[f.id] || {})[String(k)]);
        col = scaleC(col, o.brightness);
        const [R, G, B] = col.map(Math.round), dot = Math.max(2.5, Math.min(6, 120 / f.count));
        const g = ctx.createRadialGradient(px, py, 0, px, py, dot * 3); g.addColorStop(0, `rgba(${R},${G},${B},.5)`); g.addColorStop(1, `rgba(${R},${G},${B},0)`);
        ctx.fillStyle = g; ctx.fillRect(px - dot * 3, py - dot * 3, dot * 6, dot * 6);
        ctx.fillStyle = `rgb(${R},${G},${B})`; ctx.beginPath(); ctx.arc(px, py, dot, 0, Math.PI * 2); ctx.fill();
        V.hits.push({ x: px, y: py, f: f.id, k, r: dot + 4 });
      }
      ctx.fillStyle = css("--muted"); ctx.font = "11px " + css("--font"); ctx.textAlign = "center";
      const maxCh = Math.max(6, Math.floor(cell / 6.5));
      ctx.fillText(f.label.length > maxCh ? f.label.slice(0, maxCh - 1) + "…" : f.label, cx, cy + (f.kind === "fan" ? r + 26 : 30));
      V.hits.push({ x: cx, y: cy, f: f.id, k: null, r: r * 0.6 });
    });
  };

  const at = (e) => { const b = cv.getBoundingClientRect(); const x = e.clientX - b.left, y = e.clientY - b.top; return V.hits.find(hh => Math.hypot(hh.x - x, hh.y - y) <= hh.r); };
  let down = false;
  const paintAt = (e) => {
    const hit = at(e);
    if (!hit) return;
    if (V.painting && hit.k != null) { (V.paint[hit.f] ||= {})[String(hit.k)] = page.o.color; V.savePaint(); }
    else if (!V.painting || hit.k == null) { V.sel = hit.f; V.drawSide(); }
  };
  cv.addEventListener("pointerdown", e => { down = true; paintAt(e); });
  cv.addEventListener("pointermove", e => { if (down && V.painting) paintAt(e); });
  window.addEventListener("pointerup", () => { down = false; });

  V.el = root;
  V.load();
  return V;
}
