/* Small UI toolkit: element builder, icons, charts, gauge, toasts. No external libraries. */
"use strict";

// ------------------------------------------------------------------ element builder
// h("div.card#id", {onclick, style:{...}, ...attrs}, ...children)
function h(sel, attrs, ...kids) {
  const m = sel.match(/^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i);
  const el = document.createElement((m && m[1]) || "div");
  if (m && m[2]) for (const p of m[2].match(/[.#][\w-]+/g)) {
    if (p[0] === ".") el.classList.add(p.slice(1)); else el.id = p.slice(1);
  }
  if (attrs && (attrs.nodeType || typeof attrs !== "object" || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) { if (sv == null) continue; if (sk.startsWith("--")) el.style.setProperty(sk, sv); else el.style[sk] = sv; }
    }
    else if (k === "html") el.innerHTML = v;
    else if (k === "class") el.className += " " + v;
    else if (k in el && k !== "list") { try { el[k] = v; } catch { el.setAttribute(k, v); } }
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ------------------------------------------------------------------ icons (simple stroke icons)
const ICON_PATHS = {
  dash: "M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z",
  chip: "M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  pulse: "M3 12h4l3-8 4 16 3-8h4",
  gauge: "M12 14l4-4M3.5 17a9 9 0 1 1 17 0M12 5v2M5 12h2M17 12h2",
  flame: "M12 22c4 0 7-3 7-7 0-5-5-7-5-12-3 2-4 5-4 7-1-1-2-2-2-4-2 2-3 5-3 9 0 4 3 7 7 7z",
  light: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z",
  fan: "M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0M12 10c0-4 1-7 4-7 2 0 3 2 2 4l-4 4M14 12c4 0 7 1 7 4 0 2-2 3-4 2l-4-4M12 14c0 4-1 7-4 7-2 0-3-2-2-4l4-4M10 12c-4 0-7-1-7-4 0-2 2-3 4-2l4 4",
  sliders: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  heart: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 16v-4M12 8h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  play: "M6 4l14 8-14 8z",
  stop: "M6 6h12v12H6z",
  refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
  download: "M12 3v12M7 10l5 5 5-5M5 21h14",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  cpu: "M6 6h12v12H6zM9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4",
  gpu: "M2 7h20v10H2zM6 17v3M10 17v3M7 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0M15 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
  ram: "M3 7h18v8H3zM7 15v3M11 15v3M15 15v3M19 15v3M7 10v2M11 10v2M15 10v2",
  disk: "M4 4h16v16H4zM12 13m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M12 13h.01M16 7h.01",
  net: "M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a15 15 0 0 1 20 0M12 20h.01",
  board: "M3 3h18v18H3zM7 7h4v4H7zM15 7h2M15 11h2M7 15h10",
  monitor: "M2 4h20v13H2zM8 21h8M12 17v4",
  sound: "M11 5L6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14",
  sys: "M4 4h16v12H4zM2 20h20",
  keyboard: "M2 6h20v12H2zM6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10",
  mouse: "M12 2a6 6 0 0 0-6 6v8a6 6 0 0 0 12 0V8a6 6 0 0 0-6-6zM12 6v4",
  strip: "M2 10h20v4H2zM6 12h.01M10 12h.01M14 12h.01M18 12h.01",
  power: "M18.4 6.6a9 9 0 1 1-12.8 0M12 2v10",
  bolt: "M13 2L3 14h9l-1 8 10-12h-9z",
  thermo: "M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  overlay: "M3 5h18v14H3zM6 8h5v3H6z",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  rocket: "M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2M12 15l-3-3M9 12c1-5 5-9 11-9 0 6-4 10-9 11M15 9h.01",
  undo: "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11",   // Lucide "undo-2" (ISC licence)
  star: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",   // Lucide "star" (ISC)
  back: "M19 12H5M12 19l-7-7 7-7",                                                  // Lucide "arrow-left" (ISC)
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",   // Lucide "circle-help" (ISC)
  minimise: "M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0",
  maximise: "M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  palette: "M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-.9-.6-1.3-.6-2.1 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3zM7.5 12a1.2 1.2 0 1 0 0-.01M10 7.5a1.2 1.2 0 1 0 0-.01M14.5 7.5a1.2 1.2 0 1 0 0-.01",
  speed: "M12 14l4-6M3.5 17a9 9 0 1 1 17 0",
  bench: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  link: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
  logo: "M12 2l10 10-10 10L2 12z",
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  move: "M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3",
  report: "M9 17v-6M13 17V7M17 17v-3M4 3h16v18H4z",
};
function icon(name, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  if (cls) svg.setAttribute("class", cls);
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.info);
  svg.append(p);
  return svg;
}

// ------------------------------------------------------------------ formatting
const fmt = {
  n: (v, d = 0, u = "") => v == null ? "—" : `${Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}${u}`,
  bytes(b) { if (b == null) return "—"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (Math.abs(b) >= 1024 && i < 4) { b /= 1024; i++; } return `${b.toFixed(i ? 1 : 0)} ${u[i]}`; },
  rate(b) { return b == null ? "—" : fmt.bytes(b) + "/s"; },
  time(s) { s = Math.floor(s || 0); const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; },
};
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function tempColor(t) { return t == null ? css("--muted") : t >= 85 ? css("--bad") : t >= 72 ? css("--warn") : css("--good"); }

// ------------------------------------------------------------------ toasts
function toast(msg, bad = false) {
  let box = $(".toasts");
  if (!box) { box = h("div.toasts"); document.body.append(box); }
  const t = h("div.toast" + (bad ? ".bad" : ""), msg);
  box.append(t);
  setTimeout(() => t.remove(), 4500);
  if (typeof UndoBtn !== "undefined") setTimeout(() => UndoBtn.refresh(), 150);     // something probably changed
}

// ------------------------------------------------------------------ canvas helpers
function fitCanvas(c) {
  const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width * dpr)), hgt = Math.max(1, Math.round(r.height * dpr));
  if (c.width !== w || c.height !== hgt) { c.width = w; c.height = hgt; }
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return [ctx, r.width, r.height];
}

/* Sparkline: data = [[t, v], ...]; t in seconds relative to now (negative) */
function drawSpark(c, data, color, { max = null, min = 0, window = 120 } = {}) {
  const [ctx, w, hh] = fitCanvas(c);
  ctx.clearRect(0, 0, w, hh);
  if (!data || data.length < 2) return;
  const ys = data.map(d => d[1]);
  const hi = max ?? Math.max(...ys) * 1.15 + 1e-6, lo = min ?? Math.min(...ys);
  const X = t => w + (t / window) * w, Y = v => hh - 3 - ((v - lo) / (hi - lo || 1)) * (hh - 6);
  const g = ctx.createLinearGradient(0, 0, 0, hh);
  g.addColorStop(0, color + "55"); g.addColorStop(1, color + "00");
  ctx.beginPath();
  data.forEach(([t, v], i) => i ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v)));
  ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.lineJoin = "round"; ctx.stroke();
  ctx.lineTo(X(data[data.length - 1][0]), hh); ctx.lineTo(X(data[0][0]), hh); ctx.closePath();
  ctx.fillStyle = g; ctx.fill();
}

/* Line chart with grid + optional right axis.
   series: [{data:[[x,y]], color, dash:bool, right:bool, label}] */
function drawChart(c, series, { xLabel = "", yLabel = "", rLabel = "", yMin = null, yMax = null, rMax = null, xMin = null, xMax = null } = {}) {
  const [ctx, w, hh] = fitCanvas(c);
  ctx.clearRect(0, 0, w, hh);
  const pad = { l: 46, r: rLabel ? 56 : 14, t: 12, b: 26 };
  const all = series.filter(s => !s.right).flatMap(s => s.data);
  const allR = series.filter(s => s.right).flatMap(s => s.data);
  const xs = series.flatMap(s => s.data.map(d => d[0]));
  const x0 = xMin ?? (xs.length ? Math.min(...xs) : 0), x1 = xMax ?? (xs.length ? Math.max(...xs) : 1);
  const ys = all.map(d => d[1]).filter(v => v != null);
  let y0 = yMin ?? (ys.length ? Math.min(...ys) : 0), y1 = yMax ?? (ys.length ? Math.max(...ys) : 1);
  if (yMax == null) y1 = y1 + (y1 - y0) * 0.12 + 1;
  if (yMin == null) y0 = Math.max(0, y0 - (y1 - y0) * 0.1);
  const r1 = rMax ?? (allR.length ? Math.max(...allR.map(d => d[1])) * 1.1 : 1);
  const X = x => pad.l + (x - x0) / ((x1 - x0) || 1) * (w - pad.l - pad.r);
  const Y = y => hh - pad.b - (y - y0) / ((y1 - y0) || 1) * (hh - pad.t - pad.b);
  const YR = y => hh - pad.b - y / (r1 || 1) * (hh - pad.t - pad.b);
  ctx.font = "11px " + css("--mono"); ctx.fillStyle = css("--faint"); ctx.strokeStyle = css("--line");
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, y = Y(v);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText(Math.round(v), pad.l - 8, y + 4);
    if (rLabel) { ctx.textAlign = "left"; ctx.fillText(Math.round(r1 * i / 4), w - pad.r + 8, y + 4); }
  }
  ctx.textAlign = "center";
  for (let i = 0; i <= 5; i++) { const v = x0 + (x1 - x0) * i / 5; ctx.fillText(Math.round(v), X(v), hh - 8); }
  if (yLabel) { ctx.save(); ctx.translate(12, pad.t + 40); ctx.rotate(-Math.PI / 2); ctx.textAlign = "right"; ctx.fillText(yLabel, 0, 0); ctx.restore(); }
  if (rLabel) { ctx.save(); ctx.translate(w - 8, pad.t + 40); ctx.rotate(Math.PI / 2); ctx.textAlign = "left"; ctx.fillText(rLabel, 0, 0); ctx.restore(); }
  if (xLabel) { ctx.textAlign = "right"; ctx.fillText(xLabel, w - pad.r, hh - 8 - 12); }
  for (const s of series) {
    const pts = s.data.filter(d => d[1] != null);
    if (pts.length < 2) continue;
    ctx.beginPath();
    pts.forEach(([x, y], i) => { const px = X(x), py = s.right ? YR(y) : Y(y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.setLineDash(s.dash ? [6, 5] : []); ctx.lineWidth = s.width || 2; ctx.strokeStyle = s.color; ctx.lineJoin = "round"; ctx.stroke();
  }
  ctx.setLineDash([]);
  return { X, Y, pad, w, h: hh };
}

function switchEl(checked, onchange, disabled = false) {
  const inp = h("input", { type: "checkbox", checked, disabled, onchange: (e) => onchange(e.target.checked, e.target) });
  return h("label.switch", inp, h("span"));
}

function sliderRow(label, min, max, value, step, suffix, oninput) {
  const val = h("div.val", value + suffix);
  const r = h("input", { type: "range", min, max, step, value, oninput: (e) => { val.textContent = e.target.value + suffix; oninput(+e.target.value); } });
  return h("div.slider-row", h("div.muted", label), r, val);
}

function pageHead(title, sub, ...actions) {
  return h("div.page-head", h("div", h("h1", title), sub ? h("p", sub) : null), actions.length ? h("div.actions", actions) : null);
}

function banner(kind, iconName, html, action) {
  return h("div.banner." + kind, icon(iconName), h("div.txt", { html }), action || null);
}

function cardHead(title, ic, ...right) {
  return h("div.card-head", ic ? h("div.icon-badge", icon(ic)) : null, h("h3", title), h("div.spacer"), ...right);
}

/* ------------------------------------------------------------------ never show "null", "undefined" or "NaN"
   3.11 showed the word "null" at the top left: the top bar passed `null` (meaning "no preview badge") to a DOM
   method, and DOM methods turn null into the text "null". Two guards so that can't happen anywhere:
   1. append/prepend/replaceChildren/before/after/replaceWith skip null, undefined and false.
   2. a watcher replaces any text that is exactly null / undefined / NaN (or a number that came out as NaN) with
      a dash, and reports it in the console so it can be fixed properly (the click-through test fails on it). */
(function guardDom() {
  const clean = (args) => args.flat(Infinity).filter(a => a !== null && a !== undefined && a !== false);
  for (const proto of [Element.prototype, DocumentFragment.prototype, Document.prototype]) {
    for (const m of ["append", "prepend", "replaceChildren", "before", "after", "replaceWith"]) {
      const orig = proto[m];
      if (typeof orig !== "function" || orig.__guarded) continue;
      const wrapped = function (...a) { return orig.apply(this, clean(a)); };
      wrapped.__guarded = true;
      proto[m] = wrapped;
    }
  }
  const BAD = /(^|[^\w.-])(null|undefined|NaN)(?![\w-])/g;
  const fix = (node) => {
    const t = node.nodeValue;
    if (!t || !/null|undefined|NaN/.test(t)) return;
    const p = node.parentElement;
    if (!p || p.closest("script,style,textarea,input,code,pre,.allow-raw")) return;
    const nt = t.replace(BAD, (m, a) => a + "—");
    if (nt !== t) { console.warn("RigLab fixed missing text:", JSON.stringify(t), "in", p.className || p.tagName); node.nodeValue = nt; }
  };
  const walk = (root) => {
    if (root.nodeType === 3) return fix(root);
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) fix(n);
  };
  const start = () => {
    walk(document.body);
    new MutationObserver((ms) => { for (const m of ms) { if (m.type === "characterData") fix(m.target); else m.addedNodes.forEach(walk); } })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
/* text for a value that might be missing: safe(v) -> "—" for null/undefined/NaN/"" */
function safe(v, fallback = "—") {
  if (v === null || v === undefined || v === "" || (typeof v === "number" && !Number.isFinite(v))) return fallback;
  return String(v);
}
