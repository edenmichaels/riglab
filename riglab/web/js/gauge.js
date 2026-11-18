/* Gauge - the ONE dial/gauge used everywhere in RigLab (health dial, internet speed, temperatures, usage).
   Every gauge looks and moves the same way:
   - smooth ease-out when a result arrives (set), and smooth following for live readings (follow)
   - the number counts up with the arc
   - colour blends along the gauge's colour stops (e.g. red -> yellow -> green) and settles on the final colour
     (it never flashes past it: a 76 never turns green on the way up)
   - a soft glow that "breathes" once settled: calm for green, more noticeable for yellow and red
   - a scanning glow (sweeping arc + shimmer) while something is being measured
   - GPU-friendly: the sweep, glow and ripple are CSS transform/opacity animations; JavaScript only runs while a
     number is moving, and everything pauses when the gauge is off-screen or the window is minimised
   - Settings > Reduce animations, or Windows' own animation setting: values just fade in, nothing moves
   Gauge.create(opts) -> g with g.el, g.set(v), g.follow(v), g.scan(on, progress), g.setCenter(node), g.setSub(text)
   opts: kind "ring" (full circle) | "arc" (270°, gap at the bottom); min, max; unit; label; size (px);
         stops [[value, "good"|"warn"|"bad"], ...] or null (= the theme's highlight colour);
         scale(v) -> 0..1 (default: straight line min..max); format(v) -> text; ticks [values] (arc only);
         needle (arc only); duration (ms, default 1400). */
"use strict";

const STOPS = {
  health: [[0, "bad"], [50, "warn"], [80, "good"]],          // higher is better
  temp: [[40, "good"], [75, "warn"], [85, "bad"]],           // higher is worse (°C)
  load: null,                                                // usage: the theme's highlight colour
};

const Gauge = {
  seq: 0,
  live: new Set(),
  reduced() {
    return document.documentElement.classList.contains("reduce-motion") || matchMedia("(prefers-reduced-motion: reduce)").matches;
  },
  rgb(name) {
    const m = /^#?([0-9a-f]{6})$/i.exec(css("--" + name) || "");
    if (!m) return [128, 128, 128];
    const n = parseInt(m[1], 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  },
  mix(a, b, t) { return a.map((x, i) => Math.round(x + (b[i] - x) * Math.max(0, Math.min(1, t)))); },
  /* colour at value v along the stops; with `final`, never goes past the final value's own colour */
  colourAt(stops, v, final) {
    if (!stops || !stops.length) return Gauge.rgb("accent");
    let x = v;
    if (final != null) {
      const up = stops[stops.length - 1][0] >= stops[0][0];
      const reached = stops.filter(s => (up ? s[0] <= final : s[0] >= final));
      const cap = reached.length ? reached[reached.length - 1][0] : stops[0][0];
      x = up ? Math.min(v, cap) : Math.max(v, cap);
    }
    if (x <= stops[0][0]) return Gauge.rgb(stops[0][1]);
    for (let i = 1; i < stops.length; i++) {
      if (x <= stops[i][0]) return Gauge.mix(Gauge.rgb(stops[i - 1][1]), Gauge.rgb(stops[i][1]), (x - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]));
    }
    return Gauge.rgb(stops[stops.length - 1][1]);
  },
  stateAt(stops, v) {
    if (v == null || !Number.isFinite(+v)) return "none";
    if (!stops) return "accent";
    let st = stops[0][1];
    for (const [sv, s] of stops) if (v >= sv) st = s;
    return st;
  },

  create(opts = {}) {
    const o = Object.assign({ kind: "ring", min: 0, max: 100, unit: "", label: "", size: 220, stops: null, duration: 1400,
      format: (v) => String(Math.round(v)), ticks: null, needle: false }, opts);
    const id = ++Gauge.seq, ring = o.kind === "ring";
    const R = 88, C = 2 * Math.PI * R, sweep = ring ? 1 : 0.75, L = C * sweep, rot = ring ? -90 : 135;
    const frac = (v) => {
      if (v == null || !Number.isFinite(+v)) return 0;
      const f = o.scale ? o.scale(+v) : (+v - o.min) / ((o.max - o.min) || 1);
      return Math.max(0, Math.min(1, f));
    };
    const el = h("div.gauge2" + (ring ? ".ring" : ".arc") + (o.needle ? ".needle" : ""), { role: "img" });
    el.style.setProperty("--gsize", o.size + "px");          // (custom properties can't be set with style.x = ...)
    const tickSvg = (!ring && o.ticks) ? o.ticks.map(t => {
      const a = (rot + frac(t) * 270) * Math.PI / 180, r = R - 30;
      return `<text x="${(110 + r * Math.cos(a)).toFixed(1)}" y="${(110 + r * Math.sin(a) + 4).toFixed(1)}" text-anchor="middle">${t >= 1000 ? (t / 1000) + "k" : t}</text>`;
    }).join("") : "";
    el.innerHTML = `<div class="g-glow"></div>
      <svg class="g-svg" viewBox="0 0 220 220" aria-hidden="true">
        <circle class="g-track" cx="110" cy="110" r="${R}" fill="none" stroke-width="16" stroke-linecap="round" transform="rotate(${rot} 110 110)" stroke-dasharray="${L} ${C}"/>
        <circle class="g-arc" cx="110" cy="110" r="${R}" fill="none" stroke-width="16" stroke-linecap="round" transform="rotate(${rot} 110 110)" stroke-dasharray="0 ${C}"/>
        <g class="g-ticks">${tickSvg}</g>
        ${o.needle ? `<g class="g-needle" transform="rotate(${rot} 110 110)"><line x1="110" y1="110" x2="${110 + R - 26}" y2="110" stroke-width="4" stroke-linecap="round"/><circle cx="110" cy="110" r="7"/></g>` : ""}
        <g class="g-sparks">${[0, 1, 2, 3].map(() => `<circle r="2.2" cx="110" cy="22" opacity="0"/>`).join("")}</g>
      </svg>
      <div class="g-scan" aria-hidden="true"><svg viewBox="0 0 220 220"><defs><linearGradient id="gsc${id}" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--accent)" stop-opacity="0"/><stop offset="1" stop-color="var(--accent)" stop-opacity="1"/></linearGradient></defs>
        <circle cx="110" cy="110" r="${R}" fill="none" stroke="url(#gsc${id})" stroke-width="16" stroke-linecap="round" stroke-dasharray="120 ${C}" transform="rotate(-90 110 110)"/></svg></div>
      <div class="g-ripple"></div>
      <div class="g-mid"><div class="g-num"><span class="n">—</span><small class="u"></small></div><div class="g-sub small muted"></div><div class="g-center"></div></div>`;
    const q = (s) => el.querySelector(s);
    const arc = q(".g-arc"), num = q(".n"), unit = q(".u"), sub = q(".g-sub"), center = q(".g-center"), needle = q(".g-needle");
    const sparks = [...el.querySelectorAll(".g-sparks circle")];
    unit.textContent = o.unit || "";
    if (o.label) sub.textContent = o.label;
    const MODES = ["g-running", "g-filling", "g-follow", "st-good", "st-warn", "st-bad", "st-none", "st-accent"];
    const mode = (...c) => { el.classList.remove(...MODES); el.classList.add(...c); };
    const A = { shown: null, target: null, from: 0, t0: 0, raf: 0, visible: true, kind: "idle", p: 0 };

    const draw = (v, rgb) => {
      const f = frac(v);
      arc.setAttribute("stroke-dasharray", `${(f * L).toFixed(2)} ${C}`);
      if (needle) needle.setAttribute("transform", `rotate(${(rot + f * 270).toFixed(2)} 110 110)`);
      if (rgb) { const c = `rgb(${rgb.join(",")})`; arc.style.stroke = c; el.style.setProperty("--g-c", c); }
    };
    const text = (v) => { num.textContent = (v == null || !Number.isFinite(+v)) ? "—" : o.format(v); };
    const settle = (v, ripple) => {
      A.kind = "idle"; A.shown = v;
      const st = Gauge.stateAt(o.stops, v);
      draw(v, st === "none" ? null : (st === "accent" ? Gauge.rgb("accent") : Gauge.rgb(st)));
      text(v);
      mode("st-" + st);
      sparks.forEach(s => s.setAttribute("opacity", "0"));
      el.setAttribute("aria-label", (o.label || "Value") + ": " + num.textContent + (o.unit ? " " + o.unit : ""));
      if (ripple && !Gauge.reduced()) { const r = q(".g-ripple"); r.classList.remove("go"); void r.offsetWidth; r.classList.add("go"); }
    };
    const lead = (v) => { const a = (rot + frac(v) * 360 * sweep) * Math.PI / 180; return [110 + R * Math.cos(a), 110 + R * Math.sin(a)]; };
    const frame = (t) => {
      A.raf = 0;
      if (!A.visible || document.hidden) return;                       // paused: carries on when seen again
      if (A.kind === "scan") {
        const target = Math.max(A.p, A.goal);
        A.p += (target - A.p) * 0.06 + (A.p < target + 3 && A.p < 99 ? 0.012 : 0);   // flows, never jumps
        arc.setAttribute("stroke-dasharray", `${(A.p / 100 * L).toFixed(2)} ${C}`);
        if (o.scanNumber !== false) num.textContent = Math.floor(A.p);
        A.raf = requestAnimationFrame(frame);
      } else if (A.kind === "fill") {
        const k = Math.min(1, (t - A.t0) / A.dur), e = 1 - Math.pow(1 - k, 3);   // fast start, gentle stop
        const v = A.from + (A.target - A.from) * e;
        const rgb = Gauge.colourAt(o.stops, v, A.target);
        draw(v, rgb);
        text(v);
        if (A.sparks) {
          const [x, y] = lead(v);
          sparks.forEach((sp, i) => {
            const j = (t / 90 + i * 1.7) % 4, ang = i * 1.6 + t / 300;
            sp.setAttribute("cx", (x + Math.cos(ang) * j * 2.2).toFixed(1));
            sp.setAttribute("cy", (y + Math.sin(ang) * j * 2.2).toFixed(1));
            sp.setAttribute("opacity", k < 0.95 ? (0.85 - j * 0.2).toFixed(2) : "0");
            sp.setAttribute("fill", `rgb(${rgb.join(",")})`);
          });
        }
        if (k < 1) A.raf = requestAnimationFrame(frame); else settle(A.target, A.sparks);
      } else if (A.kind === "follow") {
        const d = A.target - A.shown;
        A.shown += d * 0.2;                                            // smooth chase of a live reading
        if (Math.abs(d) < Math.max(0.05, (Math.abs(o.max - o.min) || 1) * 0.003)) A.shown = A.target;
        draw(A.shown, Gauge.colourAt(o.stops, A.shown));
        text(A.shown);
        if (A.shown !== A.target) A.raf = requestAnimationFrame(frame);
        else { A.kind = "idle"; el.classList.remove("g-follow"); el.classList.remove("st-good", "st-warn", "st-bad", "st-none", "st-accent"); el.classList.add("st-" + Gauge.stateAt(o.stops, A.shown)); }
      }
    };
    const kick = () => { if (!A.raf && A.visible && !document.hidden && A.kind !== "idle") A.raf = requestAnimationFrame(frame); };

    const g = {
      el, opts: o,
      /* a result arrived: ease from the old value (or opts.from) to v, counting up, blending colour, then settle */
      set(v, opt = {}) {
        if (v == null || !Number.isFinite(+v)) { A.kind = "idle"; A.shown = null; draw(0, null); text(null); mode("st-none"); return g; }
        v = +v;
        const from = opt.from != null ? +opt.from : (A.kind === "scan" ? (opt.fromScan ?? 0) : (A.shown ?? o.min));
        if (Gauge.reduced() || opt.instant || from === v) {
          settle(v, false);
          if (!opt.instant) { el.classList.add("g-fade"); setTimeout(() => el.classList.remove("g-fade"), 600); }
          return g;
        }
        A.kind = "fill"; A.from = from; A.target = v; A.t0 = performance.now(); A.sparks = opt.sparks !== false;
        draw(from, Gauge.colourAt(o.stops, from, v)); text(from);            // first frame straight away (no stale number)
        A.dur = Math.max(500, o.duration * Math.min(1, 0.35 + Math.abs(frac(v) - frac(from)) * 1.2));
        mode("g-filling");
        kick();
        return g;
      },
      /* a live reading (temperatures every second, speed during a test): glide to it */
      follow(v) {
        if (v == null || !Number.isFinite(+v)) return g.set(null);
        v = +v;
        const range = Math.abs(o.max - o.min) || 1;
        const tiny = A.shown != null && A.kind !== "follow" && Math.abs(v - A.shown) < range * 0.01;   // sensor wobble: no animation
        if (A.shown == null || Gauge.reduced() || tiny) { A.kind = "idle"; A.shown = v; draw(v, Gauge.colourAt(o.stops, v)); text(v); mode("st-" + Gauge.stateAt(o.stops, v)); return g; }
        A.target = v;
        if (A.kind !== "follow") { A.kind = "follow"; mode("g-follow"); }
        kick();
        return g;
      },
      /* something is being measured: sweeping glow, and progress (0..1) that flows smoothly */
      scan(on, progress = null) {
        if (on) {
          if (A.kind !== "scan") { A.kind = "scan"; A.p = (progress || 0) * 100; mode("g-running"); arc.style.stroke = "var(--accent)"; el.style.setProperty("--g-c", "var(--accent)"); }
          A.goal = (progress || 0) * 100;
          if (Gauge.reduced()) { A.p = A.goal; arc.setAttribute("stroke-dasharray", `${(A.p / 100 * L).toFixed(2)} ${C}`); if (o.scanNumber !== false) num.textContent = Math.floor(A.p); }
          else kick();
        } else if (A.kind === "scan") { A.kind = "idle"; el.classList.remove("g-running"); }
        return g;
      },
      get value() { return A.shown; },
      get busy() { return A.kind !== "idle"; },
      setCenter(node) { center.replaceChildren(...(node ? [node] : [])); el.classList.toggle("has-center", !!node); return g; },
      setSub(t) { sub.textContent = t == null ? "" : String(t); return g; },
      setUnit(t) { unit.textContent = t == null ? "" : String(t); return g; },
      setFormat(fn) { o.format = fn; return g; },
      destroy() { io.disconnect(); Gauge.live.delete(g); if (A.raf) cancelAnimationFrame(A.raf); A.raf = 0; },
    };
    const io = new IntersectionObserver((es) => { A.visible = es.some(e => e.isIntersecting); el.classList.toggle("paused", !A.visible); kick(); });
    io.observe(el);
    Gauge.live.add(g);
    g._kick = () => { el.classList.toggle("paused", document.hidden || !A.visible); kick(); };
    return g;
  },
};
document.addEventListener("visibilitychange", () => { for (const g of Gauge.live) { if (!g.el.isConnected) g.destroy(); else g._kick(); } });

/* Older code calls gauge(value, max, colour, unit) - it's the shared Gauge now (live temperature dials). */
function gauge(value, max, color, unit) {
  const g = Gauge.create({ kind: "arc", max, unit, size: 150, stops: unit === "°C" ? STOPS.temp : null });
  g.follow(value);
  g.el.update = (v) => g.follow(v);
  g.el.gauge = g;
  return g.el;
}
