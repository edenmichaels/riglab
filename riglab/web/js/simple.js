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
/* 3.12: keys open from a small "?" button instead of always taking up space. */
function keyButton(label, body) {
  const pop = h("div.key-pop.hide", { role: "dialog", "aria-label": label }, h("div.small.muted", { style: { marginBottom: "6px", fontWeight: 600 } }, label), body);
  const btn = h("button.key-q", { type: "button", title: label, "aria-label": label, "aria-expanded": "false",
    onclick: (e) => {
      e.stopPropagation();
      const open = pop.classList.toggle("hide") === false;
      btn.setAttribute("aria-expanded", String(open));
      if (open) setTimeout(() => document.addEventListener("click", function off(ev) {
        if (!pop.contains(ev.target)) { pop.classList.add("hide"); btn.setAttribute("aria-expanded", "false"); document.removeEventListener("click", off); }
      }), 0);
    } }, icon("help"));
  return h("span.key", btn, pop);
}
function colourKey(opts = {}) {
  const L = XD.legend || {};
  const rows = [h("div.key-row", dot("good"), L.good), h("div.key-row", dot("warn"), L.warn), h("div.key-row", dot("bad"), L.bad),
    opts.grey === false ? null : h("div.key-row", dot("none"), L.none)];
  const risk = opts.risk ? [h("div.key-sep"), ...["None", "Low", "Medium", "High"].map(r => h("div.key-row", riskPill(r), h("span", XD.risks[r])))] : [];
  const extra = (opts.extra || []).map(([ic, txt]) => h("div.key-row", typeof ic === "string" ? h("span.key-ic", icon(ic)) : ic, txt));
  return keyButton(opts.label || (opts.risk ? "What do the colours and risk levels mean?" : "What do the colours mean?"),
    h("div.key-body", ...rows, ...risk, ...(extra.length ? [h("div.key-sep"), ...extra] : [])));
}
function riskKey() {
  return keyButton("What do the risk levels mean?", h("div.key-body", ...["None", "Low", "Medium", "High"].map(r => h("div.key-row", riskPill(r), h("span", XD.risks[r])))));
}

// ------------------------------------------------------------------ health dial (shared by Home and PC Health)
const Health = {
  last: null, history: [], running: false, loaded: false, subs: new Set(), job: null, timer: null,
  async load(force) {
    if (this.loaded && !force) return this.emit();
    try { const r = await App.api.health_last(); this.last = r.last; this.history = r.history || []; } catch { /* keep */ }
    try { const st = await App.api.health_status(); if (st && st.running) { this.job = st; this.running = st.kind !== "repair"; this.poll(); } } catch { /* none */ }
    this.loaded = true; this.emit();
  },
  /* kind: "quick" or "full". Runs in the background; progress comes from health_status() every second. */
  async run(kind = "quick") {
    if (this.job && this.job.running) return;
    let st;
    try { st = await App.api.health_start(kind); } catch (e) { toast("The check couldn't start: " + e, true); return; }
    this.job = st; this.running = true; this.emit(); this.poll();
  },
  async fix(id) {
    const r = await App.api.health_fix(id);
    toast(r.msg, !r.ok);
    if (r.ok && r.running) { this.job = r; this.emit(); this.poll(); }
    return r;
  },
  poll() {
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      let st;
      try { st = await App.api.health_status(); } catch { st = null; }
      if (!st) return this.poll();
      this.job = st;
      if (!st.running) {
        if (st.kind !== "repair" && st.result) {
          this.prev = this.last && this.last.score != null ? this.last.score : null;
          this.finishedAt = Date.now();
          this.last = st.result;
          if (st.result.score != null) this.history.push({ time: st.result.time, score: st.result.score, kind: st.result.kind });
          toast(st.result.summary);
        } else if (st.cancelled) toast("Check cancelled. Nothing was saved.");
        else if (st.kind === "repair") toast((st.items[0] || {}).say || "Repair finished");
        this.running = false; this.emit();
        if (st.kind === "repair") this.job = null;
        return;
      }
      this.emit(); this.poll();
    }, 1000);
  },
  async cancel() { try { await App.api.health_cancel(); } catch { /* ignore */ } },
  emit() { for (const f of [...this.subs]) f(); },
};

function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} hour${Math.round(s / 3600) === 1 ? "" : "s"} ago`;
  return `${Math.round(s / 86400)} days ago`;
}

/* healthDial({ link, both }) - the 0-100 dial on Home and PC Health. It's the shared Gauge (gauge.js), so it
   looks and moves exactly like every other dial: scanning glow while a check runs, then it fills from the old
   score (0 the first time), counts up, blends red -> yellow -> green and settles with a breathing glow. */
function healthDial(opts = {}) {
  const box = h("div.hdial-wrap");
  const g = Gauge.create({ kind: "ring", stops: STOPS.health, label: "PC health", unit: "%", size: opts.size || 220 });
  const ring = g.el;
  if (opts.link) {
    ring.classList.add("link");
    Object.assign(ring, { tabIndex: 0, title: "Open PC Health", onclick: () => go("dashboard"), onkeydown: (e) => { if (e.key === "Enter") go("dashboard"); } });
    ring.setAttribute("role", "button");
  }
  const none = h("div.hdial-none", "Not checked yet");
  const say = h("div.hdial-say"), buttons = h("div");
  box.append(ring, say, buttons);
  let mounted = false, was = null;
  const draw = () => {
    if (mounted && !box.isConnected) { Health.subs.delete(draw); g.destroy(); return; }
    if (box.isConnected) mounted = true;
    const r = Health.last, running = Health.running, job = Health.job || {};
    const v = r && r.score != null ? r.score : null;
    if (running) {
      g.scan(true, job.progress || 0);
      g.setSub(job.kind === "full" ? "Full check" : "Quick check");
      g.setCenter(null);
    } else if (v == null) {
      g.scan(false); g.set(null); g.setSub(""); g.setCenter(none);
    } else {
      g.setCenter(null); g.setSub("PC health");
      if (was === "running") { g.scan(false); g.set(v, { from: Health.prev ?? 0 }); }     // new result: old score -> new score
      else if (g.value == null && !g.busy) g.set(v, { from: 0 });                         // first time on screen: fill up
      else if (g.value !== v && !g.busy) g.set(v);
    }
    was = running ? "running" : (v == null ? "none" : "done");
    ring.setAttribute("aria-label", running ? "Checking your PC" : v == null ? "PC health: not checked yet" : `PC health ${v} out of 100`);
    say.textContent = running ? "Checking your PC. You can keep using it while this runs." : v == null ? "Run a quick check to get a health score for your PC." : (r.summary || "");
    buttons.replaceChildren(running ? h("div.stack", { style: { gap: "8px", alignItems: "center" } },
        h("div.small", (job.step || "Starting…") + (job.count ? ` (step ${job.index} of ${job.count})` : "")),
        h("div.small.muted", job.eta_text || ""),
        h("button.btn.sm", { onclick: () => Health.cancel() }, icon("stop"), "Cancel"))
      : h("div.row", { style: { gap: "10px", justifyContent: "center", flexWrap: "wrap" } },
        v != null ? h("span.small.muted", (r.kind === "full" ? "Full check " : "Quick check ") + ago(r.time) + ".") : null,
        actionBtn("health.quick", () => Health.run("quick"), { cls: v == null ? "primary" : "sm", icon: "heart", always: true, label: v == null ? "Run a quick check" : "Quick check" }),
        opts.both ? actionBtn("health.full", () => Health.run("full"), { cls: "sm", icon: "search", always: true }) : null));
  };
  Health.subs.add(draw);
  draw();
  Health.load();
  return box;
}

// ------------------------------------------------------------------ presets (Home)
function presetCards(onChanged, filter = {}) {
  const box = h("div.preset-row", h("div.small.muted", "Loading…"));
  const draw = async () => {
    let st;
    try { st = await App.api.preset_state(); } catch { box.replaceChildren(h("div.small.muted", "Presets aren't available right now.")); return; }
    const cards = st.cards.filter(c => (!filter.only || filter.only.includes(c.id)) && (!filter.except || !filter.except.includes(c.id)));
    box.replaceChildren(...cards.map(c => {
      const on = st.active === c.id;
      return h("button.preset" + (on ? ".on" : ""), { "aria-pressed": on, onclick: () => presetPanel(c.id, () => { draw(); if (onChanged) onChanged(); }) },
        h("div.icon-badge", icon(c.icon)),
        h("div.preset-name", c.name, on ? h("span.pill.good", "In use") : null),
        h("div.small.muted", c.desc));
    }));
    if (!st.active && !filter.except) box.append(h("div.small.muted.preset-note", "None of these match your settings right now - you're using your own mix. Pick one to switch."));
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

// ------------------------------------------------------------------ Simple view: a door into Advanced view
/* A card for a feature that's only shown in Advanced view: switches view and goes straight there. */
function openAdvanced(page, opts = {}) {
  if (opts.tab && App.pages[page]) App.pages[page].tab = opts.tab;
  setView("advanced", false).then(() => go(page, opts.focus ? { focus: opts.focus } : {}));
}
function advLink(name, page, opts = {}) {
  return h("div.adv-link", { role: "button", tabIndex: 0, "data-adv": page + (opts.focus ? "#" + opts.focus : ""),
    onclick: () => openAdvanced(page, opts), onkeydown: (e) => { if (e.key === "Enter") openAdvanced(page, opts); } },
    h("span.icon-badge", icon(opts.icon || "sliders")),
    h("div", { style: { minWidth: 0 } }, h("div", h("b", name), " - this is an advanced feature."), opts.desc ? h("div.small.muted", opts.desc) : null),
    h("span.adv-go", "Open in Advanced view →"));
}
