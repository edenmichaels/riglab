/* Home (3.12, calmer): only the health dial, the main presets (the rest under "More presets"), a quick lighting
   control, and up to 4 pinned tools (the star on a Tools tile). Anything else is one tap away in Tools. */
"use strict";

const MAIN_PRESETS = ["gaming", "balanced", "quiet", "power_saver"];

App.pages.home = {
  render(el) {
    this.el = el;
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    this.notes = h("div");
    this.light = h("div.card.home-light", h("div.small.muted", "Lighting…"));
    this.pins = h("div");
    el.append(this.notes,
      h("div.home-calm",
        h("div.card.home-center", h("div.small.muted", greet), healthDial({ link: true }), colourKey()),
        h("div.stack.home-side",
          this.light,
          h("div.card", cardHead("Pinned tools", "star", h("button.btn.sm.ghost", { onclick: () => go("tools") }, "All tools →")), this.pins))),
      h("div.mt", { "data-anchor": "presets" },
        h("div.row", { style: { alignItems: "baseline", gap: "12px", padding: "8px 2px 10px" } }, h("h2.home-h2", "Presets"),
          h("span.small.muted", "Set up your whole PC in one go. You'll see what changes first.")),
        presetCards(() => this.loadLight(), { only: MAIN_PRESETS }),
        details("More presets", presetCards(() => this.loadLight(), { except: MAIN_PRESETS }))));
    this.drawPins();
    this.loadLight();
    this.loadNotes();
  },
  drawPins() {
    const F = window.FEATURES || [];
    const items = Pins.get().map(id => F.find(f => f.id === id && f.tile)).filter(Boolean).slice(0, window.MAX_PINS || 4);
    this.pins.replaceChildren(items.length
      ? h("div.pin-grid", items.map(f => toolTile(f, { onPin: () => this.drawPins() })))
      : h("div.small.muted", "Nothing pinned. Tap the star on any tool in Tools to put it here."));
  },
  async loadLight() {
    let st = null;
    try { st = await App.api.light_state(); } catch { st = null; }
    if (!document.body.contains(this.el)) return;
    const running = st && st.status === "running";
    const eff = st && st.state ? st.state.effect : null;
    const on = running && eff && eff !== "Off";
    const n = st && st.devices ? st.devices.length : 0;
    if (!running && st && st.status === "starting" && (this.lightTries = (this.lightTries || 0) + 1) < 30) setTimeout(() => this.loadLight(), 2000);
    this.light.replaceChildren(cardHead("Lighting", "light", h("button.btn.sm.ghost", { onclick: () => go("lighting") }, "Open →")),
      h("div.opt", h("div", h("div.t", on ? safe(eff) : running ? "Lights off" : "Lighting not running"),
        h("div.d", running ? `${n} device${n === 1 ? "" : "s"}` : (st && (st.msg || st.error)) || "Open Lighting to start it.")),
        running ? switchEl(!!on, async (v) => {
          try { await App.api.light_set({ effect: v ? (st.last_effect || "Rainbow sweep") : "Off" }); } catch (e) { toast(String(e), true); }
          this.loadLight();
        }) : null),
      st && st.boot && st.boot.state === "warn" ? h("div.small", { style: { marginTop: "6px" } }, dot("warn"), " ", st.boot.say) : null);
  },
  async loadNotes() {
    let notes = [];
    try { notes = (await App.api.startup_notes()) || []; } catch { /* none */ }
    if (!document.body.contains(this.el)) return;
    const light = notes.filter(n => n.kind === "light");     // quiet one-liners (the full story is on PC Health)
    this.notes.replaceChildren(...light.map(n => h("div.quiet-note", dot("warn"), h("span", n.text), h("button.btn.sm.ghost", { onclick: () => go("lighting") }, "Lighting →"))));
  },
};
