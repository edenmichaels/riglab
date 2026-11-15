/* Overclocking workbench */
"use strict";

const OC_TABS = [["overview", "Overview", "dash"], ["cpu", "Processor", "cpu"], ["ram", "Memory", "ram"], ["gpu", "Graphics", "gpu"], ["gputune", "GPU tuning (live)", "sliders"], ["gpuresults", "GPU results", "report"],
  ["board", "Motherboard", "board"], ["journal", "Journal", "clock"]];
const RISK = { none: ["Safe", "good"], low: ["Low risk", "good"], medium: ["Medium risk", "warn"], high: ["Advanced", "bad"] };
const STATE_PILL = { passed: ["Passed", "good"], failed: ["Failed", "bad"], applied: ["Applied - test it", "warn"], reverted: ["Reverted", ""], stopped: ["Test stopped", ""] };
const TEST_LABEL = (t) => !t ? null : t.kind === "core_cycle" ? "Per-core test (~2 min per core)" : t.kind === "ram" ? `Memory test (${t.minutes} min)` :
  t.kind === "gpu" ? `Graphics test (${t.minutes} min)` : `CPU test (${t.minutes} min)`;

App.pages.overclock = {
  tab: "overview", sel: {},
  async render(el) {
    this.el = el;
    el.append(pageHead("Overclocking", "Step-by-step tuning for your exact hardware. RigLab tells you what to change, tests it, and keeps a journal so crashes can be traced to the change that caused them."));
    this.valBox = h("div");
    this.tabs = h("div.chips", { style: { marginBottom: "16px" } });
    this.body = h("div", h("div.empty", h("div.spinner"), h("div.mt", "Reading your hardware…")));
    el.append(this.valBox, this.tabs, this.body);
    this.st = await App.api.oc_state();
    this.drawTabs(); this.draw();
    this.pollVal();
  },
  drawTabs() {
    this.tabs.replaceChildren(...OC_TABS.map(([id, label, ic]) => h("div.chip" + (this.tab === id ? ".on" : ""), { onclick: () => { this.tab = id; this.drawTabs(); this.draw(); } },
      h("span.row", { style: { gap: "6px" } }, icon(ic), label))));
    $$("svg", this.tabs).forEach(s => { s.style.width = "14px"; s.style.height = "14px"; });
  },
  async refresh() { this.st = await App.api.oc_state(); this.draw(); },
  draw() {
    const t = this.tab;
    if (t === "overview") return this.drawOverview();
    if (t === "journal") return this.drawJournal();
    if (t === "gputune") return GpuTune.draw(this, this.body);
    if (t === "gpuresults") return GpuResults.draw(this, this.body);
    this.drawComponent(t);
  },
  progressOf(comp) {
    const steps = this.st.plans[comp]?.steps || [], pr = this.st.progress;
    const done = steps.filter(s => s.done || pr[s.id]?.state === "passed").length;
    const next = steps.find(s => !s.done && pr[s.id]?.state !== "passed");
    return { done, total: steps.length, next };
  },
  drawOverview() {
    const p = this.st.profile, r = p.ram;
    const card = (comp, title, ic, lines, extra) => {
      const pg = this.progressOf(comp);
      return h("div.card", cardHead(title, ic, h("span.pill" + (pg.done === pg.total && pg.total ? ".good" : ""), `${pg.done}/${pg.total} steps`)),
        h("div", { style: { fontWeight: 600, marginBottom: "6px" } }, lines[0]), lines.slice(1).map(l => h("div.small.muted", l)), extra || null,
        h("div.bar", { style: { margin: "14px 0 10px" } }, h("i", { style: { width: (pg.total ? pg.done / pg.total * 100 : 0) + "%" } })),
        pg.next ? h("button.btn.primary.sm", { onclick: () => { this.tab = comp; this.sel[comp] = pg.next.id; this.drawTabs(); this.draw(); } }, "Next: " + pg.next.title + " →")
          : h("span.small.muted", "All steps done."));
    };
    const ramExtra = r.rated ? h("div.row", { style: { margin: "10px 0 0", gap: "18px" } },
      h("div", h("div.small.muted", "Running"), h("div.stat-big", { style: { color: r.profile_on ? css("--good") : css("--warn") } }, r.running || "—")),
      h("div", h("div.small.muted", "Rated"), h("div.stat-big", r.rated)),
      h("span.pill." + (r.profile_on ? "good" : "warn"), r.profile_on ? "EXPO/XMP on" : "EXPO/XMP off")) : null;
    this.body.replaceChildren(
      banner("info", "info", "<b>Where changes happen:</b> CPU, memory and motherboard settings are changed in the <b>BIOS</b> (press <b>Del</b> while the PC starts). " +
        "Graphics cards (NVIDIA and AMD) are tuned live on the <b>GPU tuning</b> tab, with before/after benchmarks. " +
        "RigLab gives the exact menu path for your board, tests every step, and logs it. If the PC crashes during a test, RigLab notices on next start."),
      h("div.grid.g2",
        card("cpu", "Processor", "cpu", [p.cpu.name || "Unknown CPU", p.cpu.vendor === "amd" ? `Ryzen ${p.cpu.series || ""} · Zen ${p.cpu.zen || "?"} · ${p.cpu.platform || ""}${p.cpu.x3d ? " · X3D" : ""}` : ""]),
        card("ram", "Memory", "ram", [`${r.total || ""} ${r.type || ""}`.trim() || "Memory"], ramExtra),
        card("gpu", "Graphics", "gpu", [p.gpu.name || "Unknown GPU", p.gpu.vendor === "amd" ? `RDNA ${p.gpu.rdna || "?"} · live tuning in RigLab` : p.gpu.vendor === "nvidia" ? "Live tuning in RigLab" : ""]),
        card("board", "Motherboard", "board", [p.board.name || "Motherboard", `BIOS ${p.board.bios || "?"} (${p.board.bios_date || "?"})`])));
  },
  drawComponent(comp) {
    const plan = this.st.plans[comp], pr = this.st.progress;
    if (!plan || !plan.steps.length) { this.body.replaceChildren(h("div.card", h("div.empty", "Nothing to tune here for this hardware."))); return; }
    const selId = this.sel[comp] || (this.progressOf(comp).next || plan.steps[0]).id;
    const step = plan.steps.find(s => s.id === selId) || plan.steps[0];
    const list = h("div.stack", { style: { gap: "6px" } }, plan.steps.map((s, i) => {
      const st = s.done ? "passed" : pr[s.id]?.state;
      const ic = st === "passed" ? h("div.st.ok", icon("check")) : st === "failed" ? h("div.st.bad", icon("x")) : h("div.st.na", String(i + 1));
      return h("div.dev" + (s.id === step.id ? ".sel" : ""), { style: { gridTemplateColumns: "34px 1fr" }, onclick: () => { this.sel[comp] = s.id; this.draw(); } },
        ic, h("div", h("div.name", s.title), h("div.meta", st ? (STATE_PILL[st] || [st])[0] : RISK[s.risk || "low"][0])));
    }));
    const st = step.done ? "passed" : pr[step.id]?.state;
    const running = this.st.validation && this.st.validation.state === "running";
    const detail = h("div.card",
      h("div.row", { style: { marginBottom: "10px" } }, h("h3", { style: { margin: 0, fontSize: "18px" } }, step.title), h("div.spacer"),
        st ? h("span.pill." + (STATE_PILL[st] || ["", ""])[1], (STATE_PILL[st] || [st])[0]) : null, h("span.pill." + RISK[step.risk || "low"][1], RISK[step.risk || "low"][0])),
      h("div.small.muted", step.why),
      h("div.nav-label", { style: { padding: "16px 0 6px" } }, "Where"),
      h("div.mono", { style: { background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: "9px", padding: "10px 12px", userSelect: "text" } }, step.where),
      h("div.nav-label", { style: { padding: "16px 0 6px" } }, "Set"),
      h("div", { style: { background: "rgba(var(--accent-rgb),.07)", border: "1px solid rgba(var(--accent-rgb),.3)", borderRadius: "9px", padding: "12px 14px", fontWeight: 600, userSelect: "text" } }, step.set),
      step.note ? h("div.banner", { style: { marginTop: "14px", marginBottom: 0 } }, icon("alert"), h("div.txt.small", step.note)) : null,
      step.rollback ? h("div.small.muted", { style: { marginTop: "12px" } }, h("b", "If it fails: "), step.rollback) : null,
      step.controls ? (this.inlineBox = h("div.gt-inline", h("div.row", h("div.spinner"), h("span.small.muted", "Loading the sliders…")))) : null,
      step.bench ? h("div.row", { style: { marginTop: "14px" } }, h("button.btn.primary", { onclick: () => { this.tab = "gputune"; this.drawTabs(); this.draw(); } }, icon("bench"), "Open Performance: before & after")) : null,
      h("div.row.wrap", { style: { marginTop: "18px" } },
        step.where !== "RigLab" && !step.controls && !step.bench ? h("button.btn", { onclick: () => this.mark(step, "applied") }, icon("check"), "I've applied this") : null,
        step.test ? h("button.btn.primary", { disabled: running, onclick: () => this.validate(step) }, icon("play"), "Test it: " + TEST_LABEL(step.test)) : null,
        h("div.spacer"),
        st === "passed" || !step.test ? h("button.btn.ghost.sm", { onclick: () => this.mark(step, "passed") }, "Mark done") : null,
        h("button.btn.ghost.sm", { onclick: () => this.mark(step, "failed") }, "It crashed / didn't boot"),
        st ? h("button.btn.ghost.sm", { onclick: () => this.mark(step, "reverted") }, "I undid it") : null),
      (() => { const i = plan.steps.indexOf(step), nx = plan.steps[i + 1];
        return h("div.row", { style: { marginTop: "16px", paddingTop: "14px", borderTop: "1px solid var(--line)" } },
          i > 0 ? h("button.btn.ghost", { onclick: () => { this.sel[comp] = plan.steps[i - 1].id; this.draw(); } }, "← Previous step") : null, h("div.spacer"),
          nx ? h("button.btn" + (st === "passed" || st === "applied" ? ".primary" : ""), { onclick: () => { this.sel[comp] = nx.id; this.draw(); } }, `Next step: ${nx.title} →`)
            : h("span.small.muted", "Last step in this plan.")); })());
    if (step.controls) this.fillInline(step);
    const extra = [];
    if (comp === "cpu") extra.push(this.windowsCard());
    if (plan.limits.length) extra.push(h("div.card.mt", cardHead("Safety limits", "alert"), h("ul.small.muted", { style: { margin: 0, paddingLeft: "18px", lineHeight: "1.8" } }, plan.limits.map(l => h("li", l)))));
    this.body.replaceChildren(h("div.grid", { style: { gridTemplateColumns: "320px minmax(0,1fr)", alignItems: "start" } },
      h("div.card", { style: { padding: "12px" } }, list), h("div", detail, ...extra)));
  },
  async fillInline(step) {
    const box = this.inlineBox;
    const st = await App.api.gpu_tune_state();
    if (!document.body.contains(box)) return;
    const caps = st.caps || {}, draft = {};
    const keys = step.controls.filter(k => caps[k]);
    if (!keys.length) {
      box.replaceChildren(h("div.banner.warn", { style: { margin: "12px 0 0" } }, icon("alert"), h("div.txt",
        h("b", "These sliders aren't available yet. "), st.error || "RigLab couldn't get tuning controls from your graphics driver.",
        h("div.mt", h("button.btn.sm.primary", { onclick: () => { this.tab = "gputune"; this.drawTabs(); this.draw(); } }, "Run the setup check")))));
      return;
    }
    const applyBtn = h("button.btn.primary", { disabled: true }, icon("check"), "Apply to card");
    const upd = () => { const n = Object.keys(draft).length; applyBtn.disabled = !n; applyBtn.textContent = n ? `Apply ${n} change${n > 1 ? "s" : ""} to card` : "Move a slider first"; };
    applyBtn.onclick = async () => {
      const r = await App.api.gpu_tune_apply(draft);
      const bad = Object.entries(r.result || {}).filter(([, v]) => v !== "ok");
      if (bad.length) return toast("The driver refused: " + bad.map(([k, v]) => `${caps[k]?.label || k} (${v})`).join(", "), true);
      await App.api.oc_step(step.id, "applied", `Applied: ${step.title} - ` + Object.entries(draft).map(([k, v]) => `${caps[k].label} ${v}${caps[k].unit ? " " + caps[k].unit : ""}`).join(", "));
      toast("Applied to the card - now run the test");
      this.refresh();
    };
    box.replaceChildren(h("div.small.muted", { style: { padding: "10px 0 2px" } }, `Live on your ${st.gpu?.name || "card"} - nothing changes until you press Apply.`),
      ...keys.map(k => typeof caps[k].value === "boolean" ? gtToggle(k, caps[k], draft, upd) : caps[k].options ? gtSelect(k, caps[k], draft, upd) : gtSlider(k, caps[k], draft, upd)),
      h("div.row", { style: { paddingTop: "10px" } }, applyBtn, h("button.btn.ghost", { onclick: async () => { if (!confirm("Reset the graphics card to stock?")) return; await App.api.gpu_tune_reset(); toast("Stock settings restored"); this.draw(); } }, "Reset card to stock")));
    if (step.id.endsWith("power") && caps.power && caps.power.max !== caps.power.value) { draft.power = caps.power.max; box.querySelector("#gt-power") && this.fillQuick(box, "power", caps.power.max); }
    upd();
  },
  fillQuick(box, key, v) { const r = box.querySelector("#gt-" + key); if (r) { r.value = v; r.dispatchEvent(new Event("input")); } },
  windowsCard() {
    const w = this.st.windows;
    if (!w || !w.available) return h("div");
    let mode = w.boost_mode, max = w.max_state ?? 100;
    const sel = h("select", { onchange: e => { mode = +e.target.value; } }, Object.entries(w.modes).map(([k, l]) => h("option", { value: k, selected: +k === w.boost_mode }, l)));
    return h("div.card.mt", cardHead("Windows CPU behaviour (live - no BIOS needed)", "sliders"),
      h("div.sub", "Applies instantly to your current power plan. 'Disabled' boost + lower max state is a quick way to make a hot CPU much cooler."),
      h("div.opt", h("div", h("div.t", "Processor boost mode")), sel),
      h("div.opt", { style: { display: "block" } }, sliderRow("Max state", 50, 100, max, 1, "%", v => { max = v; })),
      h("div.row.mt", h("button.btn", { onclick: async () => { const r = await App.api.oc_windows_set(mode, max); toast(r.ok ? "Applied" : "Couldn't change (needs admin)", !r.ok); this.refresh(); } }, "Apply")));
  },
  async mark(step, state) {
    const words = { applied: "Applied", passed: "Done", failed: "FAILED", reverted: "Undid" };
    await App.api.oc_step(step.id, state, `${words[state]}: ${step.title} (${step.set})`);
    toast(state === "applied" ? "Logged. Now run the test." : "Logged.");
    this.refresh();
  },
  async validate(step) {
    const ok = await App.api.oc_validate(step.id, step.test.kind, step.test.minutes || 10, step.title);
    if (!ok) return toast("Another test is already running", true);
    toast("Test started - keep the PC idle. If it crashes, RigLab marks the step as failed on next start.");
    this.st.validation = { state: "running" };
    this.draw(); this.pollVal();
  },
  async pollVal() {
    clearTimeout(this.vt);
    if (!document.body.contains(this.valBox)) return;
    const v = await App.api.oc_validation();
    if (!v) { this.valBox.replaceChildren(); return; }
    const pct = Math.min(100, (v.elapsed || 0) / (v.duration || 1) * 100);
    if (v.state === "running") {
      this.valBox.replaceChildren(h("div.card.glow", { style: { marginBottom: "16px" } },
        h("div.row", h("div.spinner"), h("b", "Testing: " + (v.title || v.step)), h("div.spacer"),
          h("span.small.muted", `${fmt.time(v.elapsed)} / ${fmt.time(v.duration)}`), h("button.btn.danger.sm", { onclick: () => App.api.oc_validation_stop() }, icon("stop"), "Stop")),
        h("div.progress", { style: { margin: "12px 0 8px" } }, h("i", { style: { width: pct + "%" } })),
        h("div.small.muted", [v.core != null ? `Now testing core ${v.core}` : null, v.max_temp != null ? `CPU max ${Math.round(v.max_temp)}°C` : null, `errors: ${v.errors}`].filter(Boolean).join("  ·  "))));
      this.vt = setTimeout(() => this.pollVal(), 1000);
    } else {
      const pass = v.state === "passed";
      const pc = v.per_core && Object.keys(v.per_core).length ? h("div.row.wrap", { style: { marginTop: "10px", gap: "6px" } },
        Object.entries(v.per_core).map(([c, d]) => h("span.pill." + (d.errors ? "bad" : "good"), `Core ${c}: ${d.errors ? d.errors + " errors" : "OK"}`))) : null;
      this.valBox.replaceChildren(h("div.verdict." + (pass ? "pass" : v.state === "failed" ? "fail" : "warn"), { style: { marginBottom: "16px" } },
        h("div.st." + (pass ? "ok" : "bad"), { style: { width: "42px", height: "42px" } }, icon(pass ? "check" : "x")),
        h("div", { style: { flex: 1 } }, h("div.big", (v.title || v.step) + ": " + (v.verdict ? v.verdict[0] : v.state)), h("div", v.verdict ? v.verdict[1] : ""), pc),
        h("button.btn.ghost.sm", { onclick: () => this.valBox.replaceChildren() }, "Dismiss")));
      if (this.lastVal !== v.start) { this.lastVal = v.start; this.refresh(); }
    }
  },
  drawJournal() {
    const j = this.st.journal;
    const ic = { applied: ["sliders", "info"], passed: ["check", "good"], failed: ["x", "bad"], crash: ["alert", "bad"], detected: ["info", "info"], reverted: ["undo", ""], note: ["info", ""] };
    this.body.replaceChildren(h("div.card", cardHead("Journal", "clock", h("button.btn.sm", { onclick: async () => { const t = prompt("Add a note"); if (t) { await App.api.oc_note(t); this.refresh(); } } }, "+ Note")),
      h("div.sub", "Every change, test result, detected BIOS change and crash, newest first. Crash Center uses this to point at the change that caused a crash."),
      j.length ? h("div", j.map(e => h("div.check-item", { style: { gridTemplateColumns: "34px 1fr auto" } },
        h("div.st." + ((ic[e.kind] || ["", ""])[1] === "good" ? "ok" : (ic[e.kind] || ["", ""])[1] === "bad" ? "bad" : "na"), icon((ic[e.kind] || ["info"])[0])),
        h("div", h("div", { style: { fontWeight: 600 } }, e.text)), h("div.small.muted.mono", new Date(e.time * 1000).toLocaleString()))))
        : h("div.empty", "Nothing yet. Start with the Overview tab.")));
  },
  leave() { clearTimeout(this.vt); },
};
