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
function modal({ title, body, buttons = [{ label: "OK", value: true, cls: "primary" }], dismiss = true }) {
  return new Promise((resolve) => {
    let done = false;
    const close = (v) => { if (done) return; done = true; bg.remove(); document.removeEventListener("keydown", key); resolve(v); };
    const key = (e) => { if (e.key === "Escape" && dismiss) close(false); };
    const box = h("div.modal", { role: "dialog", "aria-modal": "true" },
      title ? h("h3", title) : null,
      h("div.modal-body", body),
      h("div.modal-btns", buttons.map(b => h("button.btn" + (b.cls ? "." + b.cls : ""), { onclick: () => close(b.value) }, b.label))));
    const bg = h("div.modal-bg", { onclick: (e) => { if (e.target === bg && dismiss) close(false); } }, box);
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
    h("div.info-k", "Can it be undone?"), h("div.info-v", a.undo));
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
