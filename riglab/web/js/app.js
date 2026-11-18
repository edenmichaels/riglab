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
  view: "simple",     // "simple" (default) or "advanced"
};

// [page, Advanced name, icon, Simple name]. No Simple name = only listed in Advanced view (still reachable).
const NAV = [
  ["home", "Home", "home", "Home"],
  ["label", "Monitor", null, "My PC"],
  ["dashboard", "Dashboard", "dash", "PC Health"],
  ["explain", "PC summary", "chip", "PC Info"],
  ["sensors", "Sensors", "pulse"],
  ["hardware", "Hardware", "chip"],
  ["crashes", "Crash Center", "alert", "Crashes & freezes"],
  ["label", "Test", null, "Tools"],
  ["benchmark", "Benchmark", "bench"],
  ["stress", "Stress test", "flame"],
  ["netspeed", "Network speed test", "net"],
  ["label", "Control"],
  ["overclock", "Overclocking", "bolt"],
  ["tweaks", "Tweaks", "sliders", "Performance Tweaks"],
  ["storage", "Storage cleanup", "trash", "Free up space"],
  ["cooling", "Cooling", "fan", "Fans"],
  ["lighting", "Lighting", "light", "Lights"],
  ["benchmark", null, "bench", "Speed test"],
  ["netspeed", null, "net", "Internet speed"],
  ["tools", "All tools", "grid", "More tools"],
  ["label", "App", null, "RigLab"],
  ["history", "Change history", "undo", "Change history"],
  ["health", "RigLab setup", "heart"],
  ["themes", "Themes", "palette", "Themes"],
  ["settings", "Settings", "gear", "Settings"],
];

function navItems() {
  const simple = isSimple();
  return NAV.map(([id, adv, ic, easy]) => [id, simple ? easy : adv, ic]).filter(([, label]) => label);
}

/* Switches instantly (no restart): redraws the menu and the current page, keeping the same tab. Saved as ui.view. */
async function setView(v, stay = true) {
  App.view = v === "advanced" ? "advanced" : "simple";
  drawNav();
  drawTopbar();
  if (stay && App.pageId) go(App.pageId);
  try { await App.api.ui_set({ view: App.view }); } catch { /* preview */ }
}

function drawTopbar() {
  const box = $("#topbar");
  if (!box) return;
  const S = isSimple();
  const b = (v, l, tip) => h("button" + ((v === "simple") === S ? ".on" : ""), { title: tip, "aria-pressed": (v === "simple") === S, onclick: () => { if ((v === "simple") !== S) setView(v); } }, l);
  box.replaceChildren(
    App.demo ? h("div.demo-tag", "Preview mode · simulated data") : null,
    h("div.spacer"),
    UndoBtn.el(),
    h("span.small.muted", { style: { marginRight: "4px" } }, "View:"),
    h("div.seg.seg-sm", { role: "group", "aria-label": "Simple or Advanced view" },
      b("simple", "Simple", "Plain words, traffic lights, risky settings hidden"),
      b("advanced", "Advanced", "Every sensor, setting and technical detail")),
    infoTip("Simple view uses plain words and hides risky settings. Advanced view shows every sensor, setting and technical detail. Nothing is removed in Simple view - switch any time."),
    h("button.btn.sm.aa", { title: "Text size", "aria-label": "Text size", onclick: (e) => textSizeMenu(e.currentTarget) },
      h("span", { style: { fontSize: "11px" } }, "A"), h("span", { style: { fontSize: "16px", fontWeight: 700 } }, "a")));
}

function textSizeMenu(anchor) {
  const old = $(".aa-menu"); if (old) { old.remove(); return; }
  const r = anchor.getBoundingClientRect(), z = +Theme.cur.text_scale || 1;
  const menu = h("div.aa-menu", { role: "menu", style: { top: (r.bottom / z + 6) + "px", right: (document.documentElement.clientWidth - r.right) / z + "px" } },
    h("div.small.muted", { style: { padding: "4px 8px 6px" } }, "Text size"),
    TEXT_SIZES.map(([v, l]) => h("button" + (+Theme.cur.text_scale === v ? ".on" : ""), { role: "menuitemradio", "aria-checked": +Theme.cur.text_scale === v,
      onclick: () => { menu.remove(); Theme.set({ text_scale: v }); } }, h("span", { style: { fontSize: (13 * v) + "px" } }, l), h("span.small.muted", Math.round(v * 100) + "%"))));
  document.body.append(menu);
  setTimeout(() => document.addEventListener("click", function off(e) { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("click", off); } }), 0);
}

// ------------------------------------------------------------------ appearance
const THEME_ACCENTS = { theme: "Theme", cyan: "Cyan", violet: "Violet", emerald: "Emerald", amber: "Amber", crimson: "Crimson", ocean: "Ocean", mono: "Graphite" };
/* [id, name, credit]. Colours live in app.css under [data-theme="id"]. Palettes are MIT-licensed. */
const THEMES = [
  ["dark", "Dark", "RigLab's own"],
  ["light", "Light", "RigLab's own"],
  ["system", "Match Windows", "Dark or Light, following Windows"],
  ["dracula", "Dracula", "Dracula Theme by Zeno Rocha and contributors (MIT licence)"],
  ["nord", "Nord", "Nord by Arctic Ice Studio and Sven Greb (MIT licence)"],
  ["catppuccin", "Catppuccin Mocha", "Catppuccin by the Catppuccin organisation (MIT licence)"],
  ["gruvbox", "Gruvbox", "Gruvbox by Pavel Pertsev (MIT licence)"],
  ["solarized", "Solarized Dark", "Solarized by Ethan Schoonover (MIT licence)"],
  ["tokyo", "Tokyo Night", "Tokyo Night by enkia (MIT licence)"],
  ["onedark", "One Dark", "One Dark by GitHub / Atom (MIT licence)"],
  ["contrast", "High Contrast", "RigLab's own, for easier reading"],
];
const TEXT_SIZES = [[0.8, "Small"], [1, "Normal"], [1.25, "Large"], [1.5, "Extra Large"]];
const Theme = {
  cur: { theme: "dark", accent: "cyan", text_scale: 1 },
  mode() { return this.cur.theme === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : this.cur.theme; },
  apply(t) {
    this.cur = Object.assign({}, this.cur, t);
    if (!THEMES.some(([id]) => id === this.cur.theme)) this.cur.theme = "dark";
    const d = document.documentElement;
    d.dataset.theme = this.mode();
    d.dataset.accent = this.cur.accent || "theme";
    d.classList.toggle("reduce-motion", !!this.cur.reduce_motion);
    const z = TEXT_SIZES.some(([v]) => v === +this.cur.text_scale) ? +this.cur.text_scale : 1;
    this.cur.text_scale = z;
    d.style.setProperty("--zoom", z);
    document.body && (document.body.style.zoom = z);
    try { localStorage.setItem("riglab.theme", JSON.stringify(this.cur)); } catch { /* ignore */ }
  },
  async set(t) {
    this.apply(t);
    try { await App.api.ui_set(t); } catch { /* preview mode */ }
    if (App.page && App.pageId) go(App.pageId);         // redraw canvases with the new colours and size
    drawTopbar();
  },
};
matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (Theme.cur.theme === "system") Theme.apply({}); });

function drawNav() {
  const box = $("#navbox");
  if (!box) return;
  box.replaceChildren(...navItems().map(([id, label, ic]) => id === "label" ? h("div.nav-label", label)
    : h("div.nav", { "data-page": id, onclick: () => go(id) }, icon(ic), h("span", label), id === "health" ? h("i.dot.hide#healthdot") : null)));
  $$(".nav").forEach(n => n.classList.toggle("active", n.dataset.page === App.pageId));
  const s = isSimple();
  $("#ft-cpu-k").textContent = s ? "Processor" : "CPU";
  $("#ft-gpu-k").textContent = s ? "Graphics" : "GPU";
  $("#ft-ram-k").textContent = s ? "Memory" : "RAM";
  const hd = $("#healthdot"); if (hd) hd.classList.toggle("hide", App.healthBad === 0);
}

function buildShell() {
  const side = h("nav.sidebar",
    h("div.brand", h("div.brand-mark", icon("logo")), h("div", h("div.brand-name", "RigLab"), h("div.brand-ver#ver", ""))),
    h("div#navbox"),
    h("div.side-foot",
      h("div.row", h("span.k#ft-cpu-k", "CPU"), h("span.v#ft-cpu", "—")),
      h("div.row", h("span.k#ft-gpu-k", "GPU"), h("span.v#ft-gpu", "—")),
      h("div.row", h("span.k#ft-ram-k", "RAM"), h("span.v#ft-ram", "—"))));
  const main = h("main.main#main");
  document.body.append(h("div.shell", side, h("div.content", h("header.topbar#topbar"), main)));
  drawNav();
  drawTopbar();
}

/* go(page, {focus: "anchor"}) - opts.focus scrolls to and highlights an element with data-anchor="anchor". */
function go(id, opts = {}) {
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
  const r = P.render(el);
  const tip = typeof Tips !== "undefined" ? Tips.banner(id) : null;
  if (tip) el.prepend(tip);
  if (App.snap && P.tick) P.tick(App.snap);
  if (opts.focus) Promise.resolve(r).then(() => setTimeout(() => {
    const a = $(`[data-anchor="${opts.focus}"]`, el);
    for (let d = a && a.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
    if (a) { a.scrollIntoView({ block: "start", behavior: "smooth" }); a.classList.add("flash"); setTimeout(() => a.classList.remove("flash"), 2200); }
  }, 350));
}

async function loop() {
  try {
    App.snap = await App.api.snapshot();
    const s = App.snap.summary;
    if (isSimple()) {
      const ft = (id, kind, v) => { const st = light(kind, v); $(id).replaceChildren(dot(st), LIGHT_WORD[st]); $(id).style.color = ""; };
      ft("#ft-cpu", "cpu_temp", s.cpu_temp); ft("#ft-gpu", "gpu_temp", s.gpu_temp); ft("#ft-ram", "ram_load", s.ram_load);
    } else {
      $("#ft-cpu").textContent = s.cpu_temp != null ? `${Math.round(s.cpu_temp)}°C` : (s.cpu_load != null ? `${Math.round(s.cpu_load)}%` : "—");
      $("#ft-cpu").style.color = tempColor(s.cpu_temp);
      $("#ft-gpu").textContent = s.gpu_temp != null ? `${Math.round(s.gpu_temp)}°C` : "—";
      $("#ft-gpu").style.color = tempColor(s.gpu_temp);
      $("#ft-ram").textContent = s.ram_load != null ? `${Math.round(s.ram_load)}%` : "—";
    }
    if (App.page && App.page.tick) App.page.tick(App.snap);
  } catch (e) { console.error(e); }
  setTimeout(loop, 1000);
}

async function refreshHealth() {
  try {
    const items = await App.api.diagnostics();
    App.healthBad = items.filter(i => i.ok === false).length;
    const hd = $("#healthdot"); if (hd) hd.classList.toggle("hide", App.healthBad === 0);
    return items;
  } catch { return []; }
}

async function start() {
  if (window.pywebview && window.pywebview.api) { App.api = window.pywebview.api; }
  else { App.api = new DemoApi(); App.demo = true; }
  App.info = await App.api.info();
  const ui = App.info.ui || {};
  Theme.apply({ theme: ui.theme || Theme.cur.theme, accent: ui.accent || Theme.cur.accent, text_scale: ui.text_scale || 1, reduce_motion: !!ui.reduce_motion });
  App.view = (App.info.view || ui.view) === "advanced" ? "advanced" : "simple";
  buildShell();
  $("#ver").textContent = "v" + App.info.version;
  const start = ui.start_page || "home";
  let first = start;
  if (start === "last") { try { first = localStorage.getItem("riglab.page") || "home"; } catch { first = "home"; } }
  App.snap = await App.api.snapshot();
  go(App.pages[first] ? first : "home");
  if (!ui.tour_done) setTimeout(() => Tour.start(), 900);      // first launch: show the walkthrough once
  loop();
  refreshHealth();
  setInterval(refreshHealth, 15000);
}

// pywebview injects its API a moment after load; fall back to demo mode in a normal browser
let started = false;
const boot = () => { if (!started) { started = true; start(); } };
window.addEventListener("pywebviewready", boot);
window.addEventListener("load", () => setTimeout(() => { if (!window.pywebview) boot(); }, 700));

/* ------------------------------------------------------------------ central Undo (top bar)
   Undo = the newest change that can be undone. The arrow lists recent changes from Change history, each with
   its own Undo. Greyed out when there's nothing to undo. Medium/High risk changes ask first. */
const UndoBtn = {
  sum: null, box: null, busy: false,
  el() {
    this.box = this.box || h("div.undo-split");
    this.render();
    this.refresh();
    return this.box;
  },
  async refresh() {
    try { this.sum = await App.api.changes_summary(); } catch { this.sum = null; }
    this.render();
  },
  render() {
    if (!this.box) return;
    const last = this.sum && this.sum.last;
    const main = h("button.btn.sm.undo-main", { disabled: !last || this.busy, "aria-label": last ? "Undo: " + last.title : "Nothing to undo",
      title: last ? "Undo: " + last.title : "Nothing to undo yet", onclick: () => last && this.undo(last) }, icon("undo"), "Undo");
    const caret = h("button.btn.sm.undo-caret", { "aria-label": "Recent changes", title: "Recent changes", "aria-haspopup": "menu",
      disabled: !(this.sum && this.sum.recent && this.sum.recent.length), onclick: (e) => this.menu(e.currentTarget) }, "▾");
    this.box.replaceChildren(main, caret);
  },
  async undo(e) {
    if (["Medium", "High"].includes(e.risk)) {
      const ok = await modal({ title: "Undo this change?", body: [h("p", h("b", e.title)), h("p", `This was a ${e.risk.toLowerCase()} risk change. Undoing it puts the setting back the way it was before.`)],
        buttons: [{ label: "Cancel", value: false }, { label: "Undo it", value: true, cls: "primary" }] });
      if (!ok) return;
    }
    this.busy = true; this.render();
    let r;
    try { r = await App.api.change_undo(e.id); } catch (x) { r = { ok: false, msg: String(x) }; }
    this.busy = false;
    toast(r.msg, !r.ok);
    if (r.ok && e.kind === "appearance") {           // put the old theme / text size back on screen too
      try { App.info = await App.api.info(); Theme.apply(App.info.ui || {}); } catch { /* preview */ }
    }
    await this.refresh();
    if (r.ok && App.pageId) go(App.pageId);
  },
  menu(anchor) {
    const old = $(".undo-menu"); if (old) { old.remove(); return; }
    const z = +Theme.cur.text_scale || 1, r = anchor.getBoundingClientRect();
    const when = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    const menu = h("div.undo-menu.aa-menu", { role: "menu", style: { top: (r.bottom / z + 6) + "px", right: (document.documentElement.clientWidth - r.right) / z + "px" } },
      h("div.small.muted", { style: { padding: "4px 8px 6px" } }, "Recent changes"),
      (this.sum.recent || []).map(e => h("div.undo-row", { role: "menuitem" },
        h("div", { style: { minWidth: 0 } }, h("div.undo-t", e.title), h("div.small.muted", when(e.time) + (e.risk && !["None", "Low"].includes(e.risk) ? ` · ${e.risk} risk` : ""))),
        e.undoable ? h("button.btn.sm", { onclick: () => { menu.remove(); this.undo(e); } }, "Undo")
          : h("span.small.muted", e.undone_by ? "Undone" : e.source === "undo" ? "" : "Can't undo"))),
      h("button.btn.sm.ghost", { style: { width: "100%", marginTop: "6px" }, onclick: () => { menu.remove(); go("history"); } }, "See all in Change history"));
    document.body.append(menu);
    setTimeout(() => document.addEventListener("click", function off(ev) { if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("click", off); } }), 0);
  },
};
setInterval(() => { if (!document.hidden && App.api) UndoBtn.refresh(); }, 5000);
