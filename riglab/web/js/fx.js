/* RigLab effect pack - live previews. Mirror of riglab/core/fx.py (keep in sync). */
"use strict";

const FX_PALETTES = {
  "Your colours": null,
  "Rainbow": [[0, [255, 0, 0]], [.17, [255, 255, 0]], [.33, [0, 255, 0]], [.5, [0, 255, 255]], [.67, [0, 0, 255]], [.83, [255, 0, 255]], [1, [255, 0, 0]]],
  "Party": [[0, [90, 0, 255]], [.25, [255, 0, 120]], [.5, [255, 90, 0]], [.75, [255, 200, 0]], [1, [90, 0, 255]]],
  "Lava": [[0, [0, 0, 0]], [.3, [120, 0, 0]], [.55, [255, 30, 0]], [.75, [255, 140, 0]], [.9, [255, 230, 120]], [1, [0, 0, 0]]],
  "Ocean": [[0, [0, 10, 60]], [.3, [0, 60, 160]], [.55, [0, 160, 200]], [.75, [40, 220, 200]], [1, [0, 10, 60]]],
  "Forest": [[0, [0, 40, 0]], [.3, [20, 120, 10]], [.55, [90, 180, 30]], [.75, [0, 90, 40]], [1, [0, 40, 0]]],
  "Heat": [[0, [0, 0, 0]], [.35, [200, 0, 0]], [.65, [255, 140, 0]], [.85, [255, 230, 60]], [1, [255, 255, 220]]],
  "Sunset": [[0, [120, 0, 60]], [.3, [255, 40, 40]], [.55, [255, 140, 0]], [.75, [255, 60, 120]], [1, [120, 0, 60]]],
  "Aurora": [[0, [0, 30, 20]], [.3, [0, 220, 100]], [.55, [0, 120, 200]], [.75, [140, 0, 220]], [1, [0, 30, 20]]],
  "Cyberpunk": [[0, [255, 0, 160]], [.33, [120, 0, 255]], [.66, [0, 220, 255]], [1, [255, 0, 160]]],
  "Ice": [[0, [0, 20, 80]], [.4, [0, 140, 255]], [.7, [180, 240, 255]], [1, [0, 20, 80]]],
};

function fxPalette(name, c1, c2) {
  const stops = FX_PALETTES[name] || [[0, c1], [.5, c2], [1, c1]];
  return (x) => {
    x = ((x % 1) + 1) % 1;
    for (let i = 1; i < stops.length; i++) {
      const [p1, a] = stops[i - 1], [p2, b] = stops[i];
      if (x <= p2) { const k = (x - p1) / Math.max(1e-6, p2 - p1); return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k]; }
    }
    return stops[stops.length - 1][1];
  };
}
function paletteSwatch(name, c1, c2, n = 24) { const p = fxPalette(name, c1, c2); return [...Array(n)].map((_, i) => p(i / n)); }

const fxHash = (i) => { const v = Math.abs(Math.sin(i * 12.9898 + 78.233) * 43758.5453); return v - Math.floor(v); };
function fxNoise2(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = fxHash(xi + yi * 57), b = fxHash(xi + 1 + yi * 57), c = fxHash(xi + (yi + 1) * 57), d = fxHash(xi + 1 + (yi + 1) * 57);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
const fxHsv = (h, s = 1, v = 1) => { h = (((h % 1) + 1) % 1) * 6; const i = Math.floor(h), f = h - i, p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6]; return [r * 255, g * 255, b * 255]; };
const fxScale = (c, k) => [c[0] * k, c[1] * k, c[2] * k];
const fxAdd = (a, b) => [Math.min(255, a[0] + b[0]), Math.min(255, a[1] + b[1]), Math.min(255, a[2] + b[2])];
const fxTri = (x) => { x = ((x % 1) + 1) % 1; return 1 - Math.abs(2 * x - 1); };
const fxRand = (n) => Math.floor(Math.random() * n);
function fxBuf(st, n) { if (!st.buf || st.buf.length !== n) st.buf = Array(n).fill([0, 0, 0]); return st.buf; }
function fxFade(b, keep) { for (let i = 0; i < b.length; i++) b[i] = fxScale(b[i], keep); }
const BLACK = [0, 0, 0];

const FX = {
  "Palette flow": [(n, pos, P) => [...Array(n)].map((_, k) => P.pal(k / n * (0.5 + P.int) - P.t * P.sp * 0.2)), "The palette scrolling along every light"],
  "Running lights": [(n, pos, P) => [...Array(n)].map((_, k) => { const w = (Math.sin(2 * Math.PI * (k / n * (1 + P.int * 4) - P.t * P.sp * 0.5)) + 1) / 2; return fxScale(P.pal(k / n), w * w); }), "Soft waves of light running along"],
  "Theater chase": [(n, pos, P) => { const step = Math.floor(P.t * P.sp * 8), gap = 2 + Math.floor(P.int * 4); return [...Array(n)].map((_, k) => (k + step) % gap === 0 ? P.pal(k / n + P.t * 0.05) : BLACK); }, "Marquee-style chasing dots"],
  "Larson scanner": [(n, pos, P) => { const head = fxTri(P.t * P.sp * 0.35) * (n - 1), w = 1 + P.int * n * 0.3; return [...Array(n)].map((_, k) => fxScale(P.c1, Math.max(0, 1 - Math.abs(k - head) / w) ** 2)); }, "Knight Rider / Cylon eye sweeping back and forth"],
  "Sinelon": [(n, pos, P, st) => { const b = fxBuf(st, n); fxFade(b, 0.80 + P.int * 0.17); b[Math.floor((Math.sin(P.t * P.sp * 1.6 + P.fi) + 1) / 2 * (n - 1) + 0.5)] = P.pal(P.t * 0.05); return [...b]; }, "A dot swinging back and forth with a fading trail"],
  "Juggle": [(n, pos, P, st) => { const b = fxBuf(st, n); fxFade(b, 0.82); const dots = 3 + Math.floor(P.int * 5);
    for (let j = 0; j < dots; j++) { const i = Math.floor((Math.sin(P.t * P.sp * (0.7 + j * 0.31)) + 1) / 2 * (n - 1) + 0.5); b[i] = fxAdd(b[i], fxScale(fxHsv(j / dots), 0.8)); } return [...b]; }, "Several coloured dots weaving in and out"],
  "BPM": [(n, pos, P) => { const beat = (Math.sin(P.t * P.sp * 2 * Math.PI) + 1) / 2; return [...Array(n)].map((_, k) => fxScale(P.pal(k / n * 0.6 + P.t * 0.1), 0.25 + 0.75 * beat * (0.6 + 0.4 * Math.sin(k * 0.6)))); }, "Palette stripes pulsing to a beat"],
  "Meteor": [(n, pos, P, st) => { const b = fxBuf(st, n); for (let i = 0; i < n; i++) if (Math.random() < 0.6) b[i] = fxScale(b[i], 0.55 + P.int * 0.35);
    const head = Math.floor((P.t * P.sp * 0.6 + P.fi * 0.21) % 1 * n); for (let j = 0; j < Math.max(1, Math.floor(n / 12)); j++) b[((head - j) % n + n) % n] = P.c1; return [...b]; }, "A meteor with a sparkling, decaying tail"],
  "Fire": [(n, pos, P, st) => { if (!st.heat || st.heat.length !== n) st.heat = Array(n).fill(0); const h = st.heat, cool = 0.05 + (1 - P.int) * 0.12;
    for (let i = 0; i < n; i++) h[i] = Math.max(0, h[i] - Math.random() * cool);
    for (let i = n - 1; i > 1; i--) h[i] = (h[i - 1] + h[i - 2] * 2) / 3;
    if (Math.random() < 0.35 + P.int * 0.5) { const j = fxRand(Math.min(3, n)); h[j] = Math.min(1, h[j] + 0.6 + Math.random() * 0.4); }
    const pal = FX_PALETTES[P.palname] ? P.pal : fxPalette("Heat", P.c1, P.c2); return h.map(x => pal(Math.min(0.99, x) * 0.999)); }, "Flickering flames (heat simulation)"],
  "Candle": [(n, pos, P, st) => { let v = st.v ?? 0.8; v += (Math.random() - 0.5) * (0.15 + P.int * 0.4) * P.sp; v = st.v = Math.max(0.35, Math.min(1, v * 0.97 + 0.8 * 0.03));
    const base = P.palname === "Your colours" ? P.c1 : [255, 120, 20]; return [...Array(n)].map((_, k) => fxScale(base, v * (0.9 + 0.1 * fxHash(k + Math.floor(P.t * 20))))); }, "Gentle candle flicker in colour 1"],
  "Confetti": [(n, pos, P, st) => { const b = fxBuf(st, n); fxFade(b, 0.90); for (let j = 0; j < 1 + Math.floor(P.int * 3); j++) if (Math.random() < 0.5 * P.sp) b[fxRand(n)] = P.pal(Math.random()); return [...b]; }, "Random pops of colour that fade away"],
  "Glitter": [(n, pos, P) => { const o = [...Array(n)].map((_, k) => P.pal(k / n - P.t * P.sp * 0.15)); for (let j = 0; j < 1 + Math.floor(P.int * 4); j++) if (Math.random() < 0.6) o[fxRand(n)] = [255, 255, 255]; return o; }, "Rainbow with white glitter sparkles"],
  "Twinklefox": [(n, pos, P) => [...Array(n)].map((_, k) => { const ph = fxHash(k + P.fi * 101), rate = 0.5 + fxHash(k * 7 + 3) * 1.5;
    let w = Math.max(0, Math.sin(2 * Math.PI * (P.t * P.sp * rate * 0.4 + ph))); w = w ** (1 + (1 - P.int) * 4); return fxScale(P.pal(fxHash(k * 13 + 1)), w); }), "Each LED twinkling on its own rhythm"],
  "Fireworks": [(n, pos, P, st) => { const b = fxBuf(st, n); fxFade(b, 0.86); st.sparks ||= [];
    if (Math.random() < 0.06 * P.sp * (0.5 + P.int)) { const c = P.pal(Math.random()), at = fxRand(n); for (let j = 0; j < 6; j++) st.sparks.push([at, (Math.random() - 0.5) * 1.6, c, 1]); }
    for (const s of st.sparks) { s[0] += s[1]; s[3] *= 0.9; const i = ((Math.floor(s[0]) % n) + n) % n; b[i] = fxAdd(b[i], fxScale(s[2], s[3])); }
    st.sparks = st.sparks.filter(s => s[3] > 0.05); return [...b]; }, "Bursts of sparks exploding and fading"],
  "Lightning": [(n, pos, P, st) => { if ((st.until ?? -1) < P.t || st.a == null) { if (Math.random() < 0.02 * P.sp * (0.5 + P.int)) { st.until = P.t + 0.05 + Math.random() * 0.2; st.a = fxRand(n); st.len = Math.max(2, Math.floor(n * (0.3 + Math.random() * 0.7))); }
      return Array(n).fill(BLACK); }
    const on = Math.random() < 0.7; return [...Array(n)].map((_, k) => on && (((k - st.a) % n) + n) % n < st.len ? [255, 255, 255] : BLACK); }, "Random white lightning strikes"],
  "Police": [(n, pos, P) => { const ph = Math.floor(P.t * P.sp * 6) % 4, fl = Math.floor(P.t * P.sp * 24) % 2 === 0, L = ph < 2 && fl, R = ph >= 2 && fl;
    return [...Array(n)].map((_, k) => k < n / 2 && L ? [255, 0, 0] : k >= n / 2 && R ? [0, 40, 255] : BLACK); }, "Red / blue emergency strobe"],
  "Heartbeat": [(n, pos, P) => { const x = (P.t * P.sp * 1.1) % 1, v = Math.max(Math.exp(-(((x - 0.05) / 0.04) ** 2)), 0.7 * Math.exp(-(((x - 0.25) / 0.05) ** 2))); return Array(n).fill(fxScale(P.c1, 0.08 + 0.92 * v)); }, "Double pulse like a heartbeat"],
  "Dissolve": [(n, pos, P, st) => { if (!st.d || st.d.length !== n) { st.d = Array(n).fill(false); st.dir = true; }
    for (let j = 0; j < 1 + Math.floor(P.int * 3); j++) if (Math.random() < 0.7 * P.sp) st.d[fxRand(n)] = st.dir;
    if (st.d.every(x => x === st.dir)) st.dir = !st.dir; return st.d.map(x => x ? P.c1 : P.c2); }, "Colour 1 and 2 dissolving into each other"],
  "Bouncing balls": [(n, pos, P) => { const o = Array(n).fill(BLACK), balls = 2 + Math.floor(P.int * 3);
    for (let j = 0; j < balls; j++) { const per = 1.2 + j * 0.37, x = ((P.t * P.sp + j * 0.53) % per) / per, hgt = 1 - (2 * x - 1) ** 2, i = Math.floor(hgt * (n - 1)); o[i] = fxAdd(o[i], P.pal(j / balls)); } return o; }, "Balls bouncing with gravity"],
  "Rain": [(n, pos, P) => pos.map(([gx, gy]) => { const col = Math.floor(gx * 12), head = (P.t * P.sp * (0.4 + fxHash(col) * 0.6) + fxHash(col * 3)) % 1.4, d = head - gy;
    const w = d >= 0 ? Math.exp(-d * (6 - P.int * 4)) : 0; return fxScale(P.palname !== "Your colours" ? P.pal(0.5 + fxHash(col) * 0.3) : P.c1, w); }), "Digital rain falling down your case"],
  "Plasma": [(n, pos, P) => { const t = P.t * P.sp, s = 2 + P.int * 6; return pos.map(([gx, gy]) => P.pal((Math.sin(gx * s + t) + Math.sin(gy * s * 0.8 - t * 1.3) + Math.sin((gx + gy) * s * 0.6 + t * 0.7) + 3) / 6 + t * 0.05)); }, "Psychedelic plasma flowing across the whole case"],
  "Noise": [(n, pos, P) => { const t = P.t * P.sp * 0.4, s = 1.5 + P.int * 5; return pos.map(([gx, gy]) => P.pal(fxNoise2(gx * s + t, gy * s - t * 0.7))); }, "Organic, lava-lamp-like palette noise"],
  "Aurora": [(n, pos, P) => { const t = P.t * P.sp * 0.25, pal = P.palname !== "Your colours" ? P.pal : fxPalette("Aurora");
    return pos.map(([gx, gy]) => { const band = fxNoise2(gx * (2 + P.int * 4) + t, t * 0.6), curtain = (Math.sin(gx * 9 + t * 3 + band * 4) + 1) / 2; return fxScale(pal(band * 0.8 + gy * 0.2), 0.2 + 0.8 * curtain * (1 - gy * 0.5)); }); }, "Northern-lights curtains drifting across"],
  "Pacifica": [(n, pos, P) => { const t = P.t * P.sp; return pos.map(([gx, gy]) => { const w = (Math.sin(gx * 7 + t * 0.9) + Math.sin(gx * 13 - t * 1.4 + gy * 3) + Math.sin(gx * 3 + t * 0.4)) / 3, k = (w + 1) / 2;
    const crest = Math.max(0, k - 0.75) * 4 * (0.5 + P.int); return fxAdd([0, 20 + 60 * k, 60 + 120 * k], [crest * 120, crest * 220, crest * 200]); }); }, "Gentle ocean waves with white crests"],
  "Ripple": [(n, pos, P) => { let g = P.shared.ripples ||= [];
    if (P.fi === 0) { if (Math.random() < 0.03 * P.sp * (0.5 + P.int * 2)) g.push([Math.random(), Math.random(), P.t, P.pal(Math.random())]); g = P.shared.ripples = g.filter(r => P.t - r[2] < 2.5); }
    return pos.map(([gx, gy]) => { let c = BLACK; for (const [rx, ry, t0, col] of g) { const age = (P.t - t0) * P.sp, d = Math.abs(Math.hypot(gx - rx, gy - ry) - age * 0.6); c = fxAdd(c, fxScale(col, Math.max(0, 1 - d * 12) * Math.max(0, 1 - age / 2.5))); } return c; }); }, "Raindrop ripples spreading across all fans"],
  "Colour waves": [(n, pos, P) => { const t = P.t * P.sp; return pos.map(([gx, gy]) => P.pal(gx * (0.5 + P.int) + Math.sin(t * 0.7 + gy * 3) * 0.2 - t * 0.08)); }, "Palette waves rolling across the case"],
};

const FX_STATE = {}, FX_SHARED = {};
/** Preview: one row of n LEDs (gx = k/n, gy = 0.5). key separates state between preview canvases. */
function fxFrame(eff, key, t, n, c1, c2, sp, br, intensity, palname) {
  const st = FX_STATE[key + "|" + eff] ||= {};
  const pos = [...Array(n)].map((_, k) => [k / n, 0.5, k / n]);
  const P = { t, sp, int: intensity ?? 0.5, c1, c2, pal: fxPalette(palname, c1, c2), palname: FX_PALETTES[palname] !== undefined ? palname : "Your colours", fi: 0, nf: 1, shared: FX_SHARED[key] ||= {} };
  const out = FX[eff][0](n, pos, P, st);
  return br < 0.999 ? out.map(c => fxScale(c, br)) : out;
}

/** LED-map preview: one fixture with real map positions [[gx, gy, ang], ...]. */
function fxFixture(eff, fid, pos, fi, nf, t, c1, c2, sp, intensity, palname) {
  const st = FX_STATE["map|" + fid + "|" + eff] ||= {};
  const P = { t, sp, int: intensity ?? 0.5, c1, c2, pal: fxPalette(palname, c1, c2), palname: FX_PALETTES[palname] !== undefined ? palname : "Your colours", fi, nf, shared: FX_SHARED.map ||= {} };
  return FX[eff][0](pos.length, pos, P, st);
}
