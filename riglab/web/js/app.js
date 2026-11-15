/* App shell: talks to Python, routes pages, runs the 1-second refresh loop. */
"use strict";

const App = {
  api: null,          // pywebview.api, or DemoApi when opened in a normal browser
  demo: false,
  snap: null,         // latest sensor snapshot
  page: null,         // current page object {render(el), tick(snap), leave()}
  pages: {},          // registered by pages_*.js
  info: {},
  healthBad: 0,
};

const NAV = [
  ["home", "Home", "home"],
  ["label", "Monitor"],
  ["dashboard", "Dashboard", "dash"],
  ["sensors", "Sensors", "pulse"],
  ["hardware", "Hardware", "chip"],
  ["crashes", "Crash Center", "alert"],
  ["label", "Test"],
  ["benchmark", "Benchmark", "bench"],
  ["stress", "Stress test", "flame"],
  ["label", "Control"],
  ["overclock", "Overclocking", "bolt"],
  ["lighting", "Lighting", "light"],
  ["cooling", "Cooling", "fan"],
  ["tweaks", "Tweaks", "sliders"],
  ["label", "App"],
  ["health", "Health check", "heart"],
  ["settings", "Settings", "gear"],
];

// ------------------------------------------------------------------ appearance
const THEME_ACCENTS = { cyan: "Cyan", violet: "Violet", emerald: "Emerald", amber: "Amber", crimson: "Crimson", ocean: "Ocean", mono: "Graphite" };
const Theme = {
  cur: { theme: "dark", accent: "cyan" },
  apply(t) {
    this.cur = Object.assign({}, this.cur, t);
    const mode = this.cur.theme === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : this.cur.theme;
    document.documentElement.dataset.theme = mode;
    document.documentElement.dataset.accent = this.cur.accent;
    try { localStorage.setItem("riglab.theme", JSON.stringify(this.cur)); } catch { /* ignore */ }
  },
  async set(t) {
    this.apply(t);
    try { await App.api.ui_set(t); } catch { /* preview mode */ }
    if (App.page && App.pageId) go(App.pageId);         // redraw canvases with the new colours
  },
};
matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (Theme.cur.theme === "system") Theme.apply({}); });

function buildShell() {
  const side = h("nav.sidebar",
    h("div.brand", h("div.brand-mark", icon("logo")), h("div", h("div.brand-name", "RigLab"), h("div.brand-ver#ver", ""))),
    NAV.map(([id, label, ic]) => id === "label" ? h("div.nav-label", label)
      : h("div.nav", { "data-page": id, onclick: () => go(id) }, icon(ic), h("span", label), id === "health" ? h("i.dot.hide#healthdot") : null)),
    h("div.side-foot",
      h("div.row", h("span.k", "CPU"), h("span.v#ft-cpu", "—")),
      h("div.row", h("span.k", "GPU"), h("span.v#ft-gpu", "—")),
      h("div.row", h("span.k", "RAM"), h("span.v#ft-ram", "—"))));
  const main = h("main.main#main");
  document.body.append(h("div.shell", side, main));
  if (App.demo) document.body.append(h("div.demo-tag", "Preview mode · simulated data"));
}

function go(id) {
  if (App.page && App.page.leave) App.page.leave();
  const P = App.pages[id];
  if (!P) return;
  $$(".nav").forEach(n => n.classList.toggle("active", n.dataset.page === id));
  const main = $("#main");
  main.innerHTML = "";
  main.scrollTop = 0;
  const el = h("div.page");
  main.append(el);
  App.page = P;
  App.pageId = id;
  try { localStorage.setItem("riglab.page", id); } catch { /* storage may be off */ }
  P.render(el);
  if (App.snap && P.tick) P.tick(App.snap);
}

async function loop() {
  try {
    App.snap = await App.api.snapshot();
    const s = App.snap.summary;
    $("#ft-cpu").textContent = s.cpu_temp != null ? `${Math.round(s.cpu_temp)}°C` : (s.cpu_load != null ? `${Math.round(s.cpu_load)}%` : "—");
    $("#ft-cpu").style.color = tempColor(s.cpu_temp);
    $("#ft-gpu").textContent = s.gpu_temp != null ? `${Math.round(s.gpu_temp)}°C` : "—";
    $("#ft-gpu").style.color = tempColor(s.gpu_temp);
    $("#ft-ram").textContent = s.ram_load != null ? `${Math.round(s.ram_load)}%` : "—";
    if (App.page && App.page.tick) App.page.tick(App.snap);
  } catch (e) { console.error(e); }
  setTimeout(loop, 1000);
}

async function refreshHealth() {
  try {
    const items = await App.api.diagnostics();
    App.healthBad = items.filter(i => i.ok === false).length;
    $("#healthdot").classList.toggle("hide", App.healthBad === 0);
    return items;
  } catch { return []; }
}

async function start() {
  if (window.pywebview && window.pywebview.api) { App.api = window.pywebview.api; }
  else { App.api = new DemoApi(); App.demo = true; }
  App.info = await App.api.info();
  const ui = App.info.ui || {};
  Theme.apply({ theme: ui.theme || Theme.cur.theme, accent: ui.accent || Theme.cur.accent });
  buildShell();
  $("#ver").textContent = "v" + App.info.version;
  const start = ui.start_page || "home";
  let first = start;
  if (start === "last") { try { first = localStorage.getItem("riglab.page") || "home"; } catch { first = "home"; } }
  App.snap = await App.api.snapshot();
  go(App.pages[first] ? first : "home");
  loop();
  refreshHealth();
  setInterval(refreshHealth, 15000);
}

// pywebview injects its API a moment after load; fall back to demo mode in a normal browser
let started = false;
const boot = () => { if (!started) { started = true; start(); } };
window.addEventListener("pywebviewready", boot);
window.addEventListener("load", () => setTimeout(() => { if (!window.pywebview) boot(); }, 700));
