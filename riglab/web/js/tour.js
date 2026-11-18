/* First-launch walkthrough (can be skipped, replayed from Settings) and first-use tips on each page
   ("Got it" hides a tip until RigLab restarts; "Don't show again" saves it in ui.tips_hidden). */
"use strict";

const TOUR = [
  { sel: "#navbox", title: "The menu", text: "Five places: Home, PC Health, Lighting, Tools and Settings. Tools has everything else - tap a tool to open it." },
  { sel: ".gsearch", title: "Search", text: "Type what you want, like 'fans' or 'speed test', to jump straight there." },
  { sel: ".topbar .seg", title: "Simple or Advanced", text: "Simple view uses plain words and hides risky settings. Advanced view shows every reading and setting. You can switch any time - nothing is lost." },
  { sel: ".aa", title: "Text size", text: "Make everything bigger or smaller." },
  { sel: ".gauge2.ring", title: "Your health score", text: "A score out of 100 for your PC. Green is good, yellow is worth checking, red needs fixing. Click it to see the full report." },
  { sel: ".home-side", title: "Lights and pinned tools", text: "Turn your lights on or off here. Tools you pin (with the star in Tools) show up here too." },
  { sel: ".preset-row", title: "Presets", text: "Set up your whole PC for gaming, quiet, work and more. You always see exactly what will change before anything happens." },
  { sel: ".undo-split", title: "Undo", text: "Undoes the last change RigLab made. The arrow lists recent changes - you can always go back." },
];

const Tour = {
  i: 0, box: null,
  async start() {
    if (App.pageId !== "home") go("home");
    await new Promise(r => setTimeout(r, 450));
    this.i = 0;
    this.show();
  },
  show() {
    this.clear();
    let step = TOUR[this.i];
    let el = step && $(step.sel);
    while (step && (!el || !el.getClientRects().length)) { this.i++; step = TOUR[this.i]; el = step && $(step.sel); }   // skip what isn't on screen
    if (!step) return this.finish();
    el.scrollIntoView({ block: "center", behavior: "instant" });
    const z = +Theme.cur.text_scale || 1;
    const r = el.getBoundingClientRect();
    const R = { left: r.left / z, top: r.top / z, width: r.width / z, height: r.height / z };
    const spot = h("div.tour-spot", { style: { left: (R.left - 6) + "px", top: (R.top - 6) + "px", width: (R.width + 12) + "px", height: (R.height + 12) + "px" } });
    const n = TOUR.length;
    const card = h("div.tour-card", { role: "dialog", "aria-label": step.title },
      h("div.small.muted", `${this.i + 1} of ${n}`), h("h3", step.title), h("p", step.text),
      h("div.row", { style: { gap: "8px" } },
        h("button.btn.sm.ghost", { onclick: () => this.finish() }, "Skip tour"), h("div.spacer"),
        this.i > 0 ? h("button.btn.sm", { onclick: () => { this.i--; this.show(); } }, "Back") : null,
        h("button.btn.sm.primary", { onclick: () => { this.i++; this.show(); } }, this.i === n - 1 ? "Finish" : "Next")));
    const vw = document.documentElement.clientWidth / z, vh = document.documentElement.clientHeight / z;
    const below = R.top + R.height + 16, cw = 340;
    card.style.left = Math.max(12, Math.min(vw - cw - 12, R.left)) + "px";
    if (below + 200 < vh) card.style.top = below + "px";
    else card.style.top = Math.max(12, R.top - 216) + "px";
    if (R.width < 260 && R.left + R.width + cw + 24 < vw) { card.style.left = (R.left + R.width + 18) + "px"; card.style.top = Math.max(12, Math.min(vh - 220, R.top)) + "px"; }
    this.box = h("div.tour", spot, card);
    document.body.append(this.box);
    card.querySelector(".btn.primary").focus();
    this.key = (e) => { if (e.key === "Escape") this.finish(); };
    document.addEventListener("keydown", this.key);
  },
  clear() { if (this.box) this.box.remove(); this.box = null; if (this.key) document.removeEventListener("keydown", this.key); },
  async finish() {
    this.clear();
    App.info.ui = Object.assign(App.info.ui || {}, { tour_done: true });
    try { await App.api.ui_set({ tour_done: true }); } catch { /* preview */ }
  },
};

// ------------------------------------------------------------------ first-use tips
const TIPS = {
  home: "Your health score is in the middle. Presets set up your whole PC in one go. Pin your favourite tools here with the star in Tools.",
  tools: "Every tool in one place. Tap a tool to open it, and the star to pin it to Home.",
  netspeed: "Press GO to test your internet. It takes about 40 seconds and uses some data.",
  overlay: "Shows FPS and temperatures on top of your games. Clicks go straight through to the game.",
  themes: "Pick how RigLab looks. Changes apply straight away.",
  dashboard: "Run a quick check for a score, or a full check (it takes longer) for a virus scan and Windows file checks too. Fix it buttons repair what they can.",
  crashes: "RigLab reads Windows' own crash records and explains what probably went wrong. Nothing is changed here.",
  tweaks: "Each switch has an (i) button that explains what it does. Every change can be undone in Change history.",
  storage: "Find what's using your space. Big files are only moved to the Recycle Bin, so you can put them back.",
  explain: "A plain-English tour of what's inside your PC and what each part is good for.",
  cooling: "Pick Quiet, Balanced or Cool for all your fans at once. RigLab's safety rules always speed the fans up if something gets too hot.",
  lighting: "Pick a colour or effect for every RGB light in your PC.",
  benchmark: "Close games and other apps first, then run the speed test. Run it again after a change to see if it helped.",
  history: "Everything RigLab changes is listed here. Press Undo to put something back the way it was.",
  settings: "Text size, warnings and start-up options. Themes have their own tab at the top.",
  sensors: "Every reading your hardware reports. Click a row to see its graph.",
  hardware: "Full details of every part in your PC, and how healthy your drives are.",
  stress: "A stress test runs your PC at full power to check it's stable. RigLab stops it by itself if anything gets too hot.",
  overclock: "Step-by-step tuning. Change one thing at a time and test after each step. Every change can be undone.",
  health: "Checks that RigLab has everything it needs. Press Fix it next to anything red.",
};
const Tips = {
  seen: new Set(),             // "Got it" this session
  hidden() { return new Set((App.info.ui || {}).tips_hidden || []); },
  banner(page) {
    const text = TIPS[page];
    if (!text || this.seen.has(page) || this.hidden().has(page)) return null;
    const b = h("div.tip", { role: "note" }, h("span.tip-ic", icon("info")), h("div.tip-txt", h("b", "Tip: "), text),
      h("button.btn.sm", { onclick: () => { this.seen.add(page); b.remove(); } }, "Got it"),
      h("button.btn.sm.ghost", { onclick: async () => {
        const list = [...this.hidden(), page];
        App.info.ui = Object.assign(App.info.ui || {}, { tips_hidden: list });
        b.remove();
        try { await App.api.ui_set({ tips_hidden: list }); } catch { /* preview */ }
      } }, "Don't show again"));
    return b;
  },
  async reset() {
    this.seen.clear();
    App.info.ui = Object.assign(App.info.ui || {}, { tips_hidden: [] });
    try { await App.api.ui_set({ tips_hidden: [] }); } catch { /* preview */ }
  },
};
