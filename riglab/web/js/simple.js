/* Simple view helpers: traffic lights, "Show details" sections, "What will this do?" (ⓘ) cards,
   and the "Are you sure?" + safety restore point step for Medium/High risk actions.
   The wording comes from explain_data.js (shared with Python). */
"use strict";

const XD = window.EXPLAIN_DATA || { risks: {}, lights: {}, actions: {} };
const GUARDED_RISKS = ["Medium", "High"];

function isSimple() { return App.view !== "advanced"; }

function act(id) {
  const a = XD.actions[id] || {};
  const risk = a.risk || "Low";
  return Object.assign({ id, label: id, undo: "", does: "", notice: "" }, a, { risk, advanced: a.advanced ?? GUARDED_RISKS.includes(risk) });
}
/* Actions marked advanced (every Medium/High risk one) are hidden in Simple view - never removed. */
function shown(id) { return !isSimple() || !act(id).advanced; }

// ------------------------------------------------------------------ traffic lights
function light(kind, v) {
  const t = (App.info && App.info.lights || XD.lights)[kind];
  if (v == null || !t) return "none";
  if (t.low_bad) return v <= t.bad ? "bad" : v <= t.warn ? "warn" : "good";
  return v >= t.bad ? "bad" : v >= t.warn ? "warn" : "good";
}
function lightSay(kind, state) { const t = (App.info && App.info.lights || XD.lights)[kind]; return (t && t.say && t.say[state]) || ""; }
function lightName(kind) { const t = (App.info && App.info.lights || XD.lights)[kind]; return (t && t.name) || kind; }
function worstLight(states) { const o = { bad: 3, warn: 2, good: 1, none: 0 }; return states.reduce((a, s) => (o[s] || 0) > o[a] ? s : a, "none"); }
const LIGHT_WORD = { good: "Good", warn: "Check", bad: "Fix", none: "—" };

function dot(state, title) { return h("span.tl." + (state || "none"), { title: title || "" }); }

/* One reading as a plain row: ● Processor temperature - Nice and cool   [optional button] */
function lightRow(kind, value, opts = {}) {
  const st = opts.state || light(kind, value);
  return h("div.tl-row", dot(st),
    h("div", { style: { minWidth: 0 } }, h("div.tl-name", opts.label || lightName(kind)), h("div.small.muted", opts.say || lightSay(kind, st))),
    opts.right || null);
}

/* Collapsible section for numbers and hardware detail. */
function details(summary, ...kids) {
  return h("details.more", h("summary", summary || "Show details"), h("div.more-body", ...kids));
}

// ------------------------------------------------------------------ dialogs
function modal({ title, body, buttons = [{ label: "OK", value: true, cls: "primary" }], dismiss = true, cls = "" }) {
  return new Promise((resolve) => {
    let done = false;
    const close = (v) => { if (done) return; done = true; bg.remove(); document.removeEventListener("keydown", key); resolve(v); };
    const key = (e) => { if (e.key === "Escape" && dismiss) close(false); };
    const box = h("div.modal" + (cls ? "." + cls : ""), { role: "dialog", "aria-modal": "true", "aria-label": title || "" },
      title ? h("h3", title) : null,
      h("div.modal-body", body),
      h("div.modal-btns", buttons.map(b => h("button.btn" + (b.cls ? "." + b.cls : ""), { onclick: () => close(b.value) }, b.label))));
    const bg = h("div.modal-bg" + (cls ? "." + cls + "-bg" : ""), { onclick: (e) => { if (e.target === bg && dismiss) close(false); } }, box);
    document.body.append(bg);
    document.addEventListener("keydown", key);
    const primary = box.querySelector(".btn.primary") || box.querySelector(".btn");
    if (primary) primary.focus();
  });
}
function busyModal(text) {
  const msg = h("div", text);
  const bg = h("div.modal-bg", h("div.modal", h("div.row", h("div.spinner"), msg)));
  document.body.append(bg);
  return { close: () => bg.remove(), set: (t) => { msg.textContent = t; } };
}

// ------------------------------------------------------------------ ⓘ cards
function riskPill(risk) {
  const cls = { None: "good", Low: "good", Medium: "warn", High: "bad" }[risk] || "warn";
  return h("span.pill." + cls, risk === "None" ? "No risk" : risk + " risk");
}
function infoCard(id, risk) {
  const a = act(id);
  risk = risk || a.risk;
  return h("div.info-card",
    h("div.info-k", "What it does"), h("div.info-v", a.does),
    h("div.info-k", "What you'll notice"), h("div.info-v", a.notice),
    h("div.info-k", "Risk"), h("div.info-v", riskPill(risk), h("span.small.muted", { style: { marginLeft: "8px" } }, XD.risks[risk] || "")),
    h("div.info-k", "Can it be undone?"), h("div.info-v", a.undo),
    h("div", { style: { gridColumn: "1 / -1" } }, riskKey()));
}
function infoBtn(id) {
  return h("button.ibtn", { type: "button", title: "What will this do?", "aria-label": "What will this do?",
    onclick: (e) => { e.stopPropagation(); e.preventDefault(); modal({ title: act(id).label, body: infoCard(id), buttons: [{ label: "Got it", value: true, cls: "primary" }] }); } }, "i");
}

// ------------------------------------------------------------------ risky actions
/* Runs fn() straight away for None/Low risk. For Medium/High: asks "Are you sure?", then makes sure there's a
   safety restore point (one from the last 24 h counts). High risk is blocked without one; Medium asks.
   Returns fn()'s result, or null if the person cancelled. */
async function guarded(id, fn, opts = {}) {
  const a = act(id), risk = opts.risk || a.risk;
  if (!GUARDED_RISKS.includes(risk)) return fn();
  const sure = await modal({ title: opts.title || "Are you sure?", body: [infoCard(id, risk),
    h("p.small.muted", { style: { marginTop: "12px" } }, "Before this change, RigLab checks for a safety restore point and makes one if needed.")],
    buttons: [{ label: "Cancel", value: false }, { label: "Yes, go ahead", value: true, cls: "primary" }] });
  if (!sure) return null;
  for (let attempt = 0; attempt < 2; attempt++) {
    const busy = busyModal("Checking for a safety restore point… this can take a minute.");
    let d;
    try { d = await App.api.restore_prepare(risk); }
    catch (e) { d = { go: risk === "High" ? "block" : "ask", msg: "RigLab couldn't check for a restore point (" + e + ")." }; }
    finally { busy.close(); }
    if (d.go === "proceed") { if (d.msg) toast(d.msg); return fn(); }
    const buttons = [];
    if (d.fix === "restore.enable") buttons.push({ label: "Turn on restore points", value: "fix", cls: d.go === "block" ? "primary" : "" });
    buttons.push({ label: d.go === "block" ? "Close" : "Cancel", value: false });
    if (d.go === "ask") buttons.push({ label: "Continue without a backup", value: "go", cls: "danger" });
    const choice = await modal({ title: d.go === "block" ? "This needs a safety backup first" : "No safety backup", body: h("p", d.msg), buttons });
    if (choice === "go") return fn();
    if (choice !== "fix") return null;
    const b = busyModal("Turning on restore points…");
    let r;
    try { r = await App.api.restore_enable(); } finally { b.close(); }
    toast(r.msg, !r.ok);
    if (!r.ok) return null;
  }
  return null;
}

/* A button labelled with the outcome, with its ⓘ. Hidden in Simple view if the action is advanced. */
function actionBtn(id, fn, opts = {}) {
  if (!shown(id) && !opts.always) return null;
  const a = act(id);
  const b = h("button.btn" + (opts.cls ? "." + opts.cls : ""), { disabled: opts.disabled,
    onclick: async () => { b.disabled = true; try { await guarded(id, fn, opts); } finally { if (document.body.contains(b)) b.disabled = !!opts.disabled; } } },
    opts.icon ? icon(opts.icon) : null, opts.label || a.label);
  return h("span.act", b, infoBtn(id));
}

/* On/off row: label + ⓘ + plain description + switch. set(v) returns true when it worked. */
function switchRow(id, checked, set, opts = {}) {
  if (!shown(id) && !opts.always) return null;
  const a = act(id);
  return h("div.opt",
    h("div", h("div.t", opts.label || a.label, " ", infoBtn(id), ...(opts.pills || [])), h("div.d", opts.desc ?? a.notice)),
    switchEl(!!checked, async (v, inp) => {
      inp.disabled = true;
      let ok = null;
      try { ok = await guarded(id, () => set(v)); } finally { inp.disabled = !!opts.disabled; }
      if (ok !== true) inp.checked = !v;           // cancelled or refused: put the switch back
    }, opts.disabled));
}

/* Plain page header (Simple view uses the friendly title/subtitle). */
function plainHead(simpleTitle, simpleSub, advTitle, advSub, ...actions) {
  return isSimple() ? pageHead(simpleTitle, simpleSub, ...actions) : pageHead(advTitle, advSub, ...actions);
}

// ------------------------------------------------------------------ small "i" with a plain explanation (no action)
function infoTip(text, title) {
  return h("button.ibtn", { type: "button", title: "What's this?", "aria-label": "What's this?",
    onclick: (e) => { e.stopPropagation(); modal({ title: title || "What's this?", body: h("p", text), buttons: [{ label: "Got it", value: true, cls: "primary" }] }); } }, "i");
}

// ------------------------------------------------------------------ keys / legends (compact: one link that expands)
function colourKey(opts = {}) {
  const L = XD.legend || {};
  const rows = [h("div.key-row", dot("good"), L.good), h("div.key-row", dot("warn"), L.warn), h("div.key-row", dot("bad"), L.bad),
    opts.grey === false ? null : h("div.key-row", dot("none"), L.none)];
  const risk = opts.risk ? [h("div.key-sep"), ...["None", "Low", "Medium", "High"].map(r => h("div.key-row", riskPill(r), h("span", XD.risks[r])))] : [];
  const extra = (opts.extra || []).map(([ic, txt]) => h("div.key-row", typeof ic === "string" ? h("span.key-ic", icon(ic)) : ic, txt));
  return h("details.key", h("summary", opts.label || (opts.risk ? "What do the colours and risk levels mean?" : "What do the colours mean?")),
    h("div.key-body", ...rows, ...risk, ...(extra.length ? [h("div.key-sep"), ...extra] : [])));
}
function riskKey() {
  return h("details.key", h("summary", "What do the risk levels mean?"),
    h("div.key-body", ...["None", "Low", "Medium", "High"].map(r => h("div.key-row", riskPill(r), h("span", XD.risks[r])))));
}

// ------------------------------------------------------------------ health dial (shared by Home and PC Health)
const Health = {
  last: null, history: [], running: false, loaded: false, subs: new Set(),
  async load(force) {
    if (this.loaded && !force) return this.emit();
    try { const r = await App.api.health_last(); this.last = r.last; this.history = r.history || []; } catch { /* keep */ }
    this.loaded = true; this.emit();
  },
  async run() {
    if (this.running) return;
    this.running = true; this.emit();
    try {
      const r = await App.api.health_quick();
      if (r && !r.busy) { this.last = r; if (r.score != null) this.history.push({ time: r.time, score: r.score }); }
    } catch (e) { toast("The check didn't finish: " + e, true); }
    this.running = false; this.emit();
  },
  emit() { for (const f of [...this.subs]) f(); },
};

function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} hour${Math.round(s / 3600) === 1 ? "" : "s"} ago`;
  return `${Math.round(s / 86400)} days ago`;
}

/* healthDial({ link: true }) - a big circular 0-100 dial. Colour follows the traffic-light rules.
   link: clicking the dial opens PC Health. Both pages use this one component, so they always match. */
function healthDial(opts = {}) {
  const box = h("div.hdial-wrap");
  let mounted = false;
  const draw = () => {
    if (mounted && !box.isConnected) { Health.subs.delete(draw); return; }
    if (box.isConnected) mounted = true;
    const r = Health.last, running = Health.running;
    const v = r && r.score != null ? r.score : null, st = running ? "none" : (r ? r.state : "none");
    const R = 88, C = 2 * Math.PI * R, pct = v == null || running ? 0 : v / 100;
    const col = { good: "var(--good)", warn: "var(--warn)", bad: "var(--bad)", none: "var(--faint)" }[st];
    const ring = h("div.hdial" + (opts.link ? ".link" : ""), {
      role: opts.link ? "button" : null, tabIndex: opts.link ? 0 : null, title: opts.link ? "Open PC Health" : null,
      onclick: opts.link ? () => go("dashboard") : null, onkeydown: opts.link ? (e) => { if (e.key === "Enter") go("dashboard"); } : null });
    ring.innerHTML = `<svg viewBox="0 0 220 220" aria-hidden="true"><circle cx="110" cy="110" r="${R}" fill="none" stroke="var(--line)" stroke-width="16"/>
      <circle cx="110" cy="110" r="${R}" fill="none" stroke="${col}" stroke-width="16" stroke-linecap="round" transform="rotate(-90 110 110)"
        stroke-dasharray="${C * pct} ${C}" style="transition:stroke-dasharray .8s, stroke .6s;filter:drop-shadow(0 0 8px ${col})"/></svg>`;
    const mid = h("div.hdial-mid");
    if (running) mid.append(h("div.spinner"), h("div.small.muted", { style: { marginTop: "10px" } }, "Checking…"));
    else if (v == null) mid.append(h("div.hdial-none", "Not checked yet"));
    else mid.append(h("div.hdial-num", { style: { color: col } }, v, h("small", "%")), h("div.small.muted", "PC health"));
    ring.append(mid);
    ring.setAttribute("aria-label", running ? "Checking your PC" : v == null ? "PC health: not checked yet" : `PC health ${v} out of 100`);
    const line = running ? "Checking temperatures, memory, space, fans, drives and crashes. This takes about 20 seconds."
      : v == null ? "Run a quick check to get a health score for your PC." : r.summary;
    box.replaceChildren(ring,
      h("div.hdial-say", line),
      running ? null : h("div.row", { style: { gap: "10px", justifyContent: "center", flexWrap: "wrap" } },
        v == null ? actionBtn("health.quick", () => Health.run(), { cls: "primary", icon: "heart", always: true })
          : [h("span.small.muted", "Checked " + ago(r.time) + "."), h("button.btn.sm.ghost", { onclick: () => Health.run() }, icon("refresh"), "Check again")]));
  };
  Health.subs.add(draw);
  draw();
  Health.load();
  return box;
}

// ------------------------------------------------------------------ presets (Home)
function presetCards(onChanged) {
  const box = h("div.preset-row", h("div.small.muted", "Loading…"));
  const draw = async () => {
    let st;
    try { st = await App.api.preset_state(); } catch { box.replaceChildren(h("div.small.muted", "Presets aren't available right now.")); return; }
    box.replaceChildren(...st.cards.map(c => {
      const on = st.active === c.id;
      return h("button.preset" + (on ? ".on" : ""), { "aria-pressed": on, onclick: () => presetPanel(c.id, () => { draw(); if (onChanged) onChanged(); }) },
        h("div.icon-badge", icon(c.icon)),
        h("div.preset-name", c.name, on ? h("span.pill.good", "In use") : null),
        h("div.small.muted", c.desc));
    }));
    if (!st.active) box.append(h("div.small.muted.preset-note", "None of these match your settings right now - you're using your own mix. Pick one to switch."));
  };
  draw();
  return box;
}

/* Preview first, never apply straight away. Apply follows the usual rules: confirm + restore point for
   Medium/High risk, logged as one change in Change history with one-click Undo. */
async function presetPanel(pid, done) {
  const busy = busyModal("Working out what this preset would change…");
  let p;
  try { p = await App.api.preset_preview(pid); } catch (e) { p = { error: String(e) }; } finally { busy.close(); }
  if (p.error) return toast(p.error, true);
  const S = isSimple();
  const sec = (title, kids) => h("div.pp-sec", h("div.info-k", title), kids);
  const body = [
    h("p.muted", { style: { marginTop: 0 } }, p.desc),
    sec("What will change", p.changes.length ? h("ul.pp-list", p.changes.map(c => h("li", c.text)))
      : h("div", "Nothing - your PC is already set up for " + p.name + ".")),
    p.skipped.length ? sec("Left as it is", h("ul.pp-list.muted", p.skipped.map(x => h("li", x)))) : null,
    p.changes.length ? sec("What you'll notice", h("ul.pp-list", p.notice.map(x => h("li", x)))) : null,
    p.changes.length ? sec("Risk", h("div", riskPill(p.risk), h("span.small.muted", { style: { marginLeft: "8px" } }, XD.risks[p.risk] || ""))) : null,
    p.changes.length ? sec("Can it be undone?", h("div", p.undo)) : null,
    p.already.length ? details("Already set (" + p.already.length + ")", h("ul.pp-list.muted", p.already.map(x => h("li", x)))) : null,
    !S && p.changes.length ? details("Show details (exact settings)", h("pre.log", p.changes.map(c => c.tech).join("\n"))) : null,
    p.changes.length ? riskKey() : null,
  ];
  const go_ = await modal({ title: p.name + " preset", body, cls: "drawer",
    buttons: p.changes.length ? [{ label: "Cancel", value: false }, { label: "Apply", value: true, cls: "primary" }] : [{ label: "Close", value: false, cls: "primary" }] });
  if (!go_) return;
  const r = await guarded("preset.apply", () => App.api.preset_apply(pid), { risk: p.risk, title: "Apply the " + p.name + " preset?" });
  if (r == null) return;
  toast(r.msg, !r.ok);
  if (done) done(r);
}
