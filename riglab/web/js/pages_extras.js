/* PC Info, and Free up space (storage clean-up). */
"use strict";

// =================================================================== PC Info
App.pages.explain = {
  async render(el) {
    this.el = el;
    el.append(plainHead("PC Info", "What's inside your PC, what each part does, and what it's good for.",
      "PC summary", "A plain-English summary of the hardware inventory. Full specs are on the Hardware page."),
      h("div", { style: { margin: "-8px 0 12px" } }, colourKey({ grey: false, label: "What do the coloured dots mean?" })));
    const box = h("div.card", h("div.empty", h("div.spinner"), h("div.mt", "Reading your hardware… (a few seconds)")));
    el.append(box);
    let r;
    try { r = await App.api.explain_pc(); } catch (e) { box.replaceChildren(h("div.empty", "RigLab couldn't read your hardware: " + e)); return; }
    if (!document.body.contains(el)) return;
    if (!r.items.length) { box.replaceChildren(h("div.empty", "RigLab couldn't read your hardware yet.")); return; }
    box.replaceChildren(...r.items.map(i => h("div.explain-item",
      h("div.icon-badge", icon(i.icon)), i.state === "none" ? h("span", { style: { width: "12px" } }) : dot(i.state, (XD.legend || {})[i.state]),
      h("div", { style: { minWidth: 0 } }, h("div.tl-name", i.title), h("div", { style: { lineHeight: 1.55, marginTop: "2px" } }, i.say),
        details(isSimple() ? "Show details" : "Technical details", h("pre.log", i.details))))),
      h("div.row.mt", h("button.btn", { onclick: () => go("hardware") }, icon("chip"), "See every detail (Hardware page)")));
  },
};

// =================================================================== Free up space
App.pages.storage = {
  async render(el) {
    this.el = el;
    el.append(plainHead("Free up space", "See what's filling your drives and clear out what you don't need. Your own files only go to the Recycle Bin, so you can get them back.",
      "Storage cleanup", "Drive space, temporary files, old Windows Update downloads and the largest files in your user folders."));
    this.top = h("div.card", h("div.empty", h("div.spinner")));
    this.junkBox = h("div.card.mt");
    this.updBox = h("div.card.mt");
    this.bigBox = h("div.card.mt", { "data-anchor": "big" });
    el.append(this.top, h("div.grid.g2", this.junkBox, this.updBox), this.bigBox);
    this.drawJunk();
    let st;
    try { st = await App.api.storage_state(); } catch (e) { this.top.replaceChildren(h("div.empty", String(e))); return; }
    if (!document.body.contains(el)) return;
    this.st = st;
    this.drawDrives(); this.drawUpdates(); this.drawBig(st.big);
    if (st.big && st.big.running) this.pollBig();
  },
  drawDrives() {
    const d = this.st.drives || [];
    this.top.replaceChildren(cardHead(isSimple() ? "Your drives" : "Drive space", "disk"),
      ...(d.length ? d.map(x => {
        const state = light("disk_free", x.pct_free);
        return h("div.tl-row", dot(state, (XD.legend || {})[state]),
          h("div", { style: { minWidth: 0 } }, h("div.tl-name", x.name), h("div.small.muted", `${fmt.bytes(x.free)} free of ${fmt.bytes(x.total)} · ${lightSay("disk_free", state)}`),
            h("div.bar", { style: { marginTop: "6px", maxWidth: "420px" } }, h("i", { style: { width: (100 - (x.pct_free || 0)) + "%", background: `var(--${state === "none" ? "accent" : state})` } }))));
      }) : [h("div.small.muted", "RigLab couldn't read your drives.")]),
      h("div", { style: { paddingTop: "8px" } }, colourKey()));
  },
  drawJunk() {
    const txt = h("div.small.muted", { style: { minHeight: "1.4em" } }, "");
    this.junkBox.replaceChildren(cardHead("Temporary files", "trash"),
      h("div.sub", "Files Windows and games made for a short time and don't need any more. Your own files are never touched."),
      h("div.row.wrap", { style: { gap: "10px" } },
        actionBtn("junk.scan", async () => { txt.textContent = "Looking…"; const r = await App.api.junk(false); txt.textContent = `${fmt.bytes(r.bytes)} can be freed (${fmt.n(r.files)} files).`; }, { icon: "search", always: true }),
        actionBtn("junk.clean", async () => { txt.textContent = "Cleaning…"; const r = await App.api.junk(true); txt.textContent = `Freed ${fmt.bytes(r.bytes)} (${fmt.n(r.files)} files).`; }, { icon: "trash", always: true })),
      txt);
  },
  drawUpdates() {
    const u = this.st.updates || {};
    const txt = h("div.small.muted", u.files ? `${fmt.bytes(u.bytes)} of old Windows update downloads (${fmt.n(u.files)} files, older than 10 days).` : "No old Windows update downloads to remove.");
    this.updBox.replaceChildren(cardHead("Old Windows update files", "download"),
      h("div.sub", "Windows keeps the downloads for updates it has already installed. They're safe to remove."),
      actionBtn("storage.updates", async () => { const r = await App.api.storage_clean_updates(); toast(r.msg, !r.ok); txt.textContent = r.ok ? `Freed ${fmt.bytes(r.bytes)}.` : r.msg; },
        { icon: "trash", always: true, disabled: !u.files }), txt);
  },
  drawBig(b) {
    const head = cardHead(isSimple() ? "Biggest files in your folders" : "Largest files (user folders)", "folder");
    const sub = h("div.sub", "Looks in Downloads, Desktop, Documents, Videos, Pictures and Music for files over 200 MB.");
    if (!b || (!b.running && !b.files)) {
      this.bigBox.replaceChildren(head, sub, actionBtn("storage.big", () => this.startBig(), { icon: "search", always: true }));
      return;
    }
    if (b.running) {
      this.bigBox.replaceChildren(head, sub, h("div.row", h("div.spinner"), h("span.small.muted", `Looking through your folders… ${Math.round(b.elapsed || 0)} s`)));
      return;
    }
    const files = b.files || [];
    this.bigBox.replaceChildren(head, sub,
      files.length ? h("div", files.map(f => h("div.file-row",
        h("span.pill", f.kind),
        h("div", { style: { minWidth: 0 } }, h("div.nm", { title: f.path }, f.name), h("div.small.muted.nm", { title: f.folder }, f.folder)),
        h("b.mono", fmt.bytes(f.size)),
        h("div.row", { style: { gap: "6px" } },
          h("button.btn.sm", { onclick: () => App.api.storage_show(f.path) }, icon("folder"), "Show"),
          actionBtn("storage.recycle", async () => {
            const yes = await modal({ title: "Move to the Recycle Bin?", body: [h("p", h("b", f.name), ` (${fmt.bytes(f.size)})`), h("p.small.muted", f.folder),
              h("p", "You can put it back from the Recycle Bin. Empty the Recycle Bin to actually free the space.")],
              buttons: [{ label: "Cancel", value: false }, { label: "Move to Recycle Bin", value: true, cls: "primary" }] });
            if (!yes) return;
            const r = await App.api.storage_recycle(f.path);
            toast(r.msg, !r.ok);
            if (r.ok) this.drawBig(await App.api.storage_big_status());
          }, { cls: "sm", label: "Recycle", always: true })))))
        : h("div.small.muted", "No files over 200 MB in your folders."),
      h("div.row.mt", { style: { gap: "10px" } }, h("button.btn.sm", { onclick: () => this.startBig() }, icon("refresh"), "Look again"),
        b.finished ? null : h("span.small.muted", "Stopped after 2 minutes - these are the biggest found so far.")));
  },
  async startBig() { this.drawBig(await App.api.storage_big_start()); this.pollBig(); },
  pollBig() {
    clearTimeout(this.t);
    this.t = setTimeout(async () => {
      if (!document.body.contains(this.el)) return;
      const b = await App.api.storage_big_status();
      this.drawBig(b);
      if (b.running) this.pollBig();
    }, 1000);
  },
};

// =================================================================== Tools: a grid of big tiles, like a phone's home screen
/* Pins: the star on a tile adds it to Home (up to 4, saved as ui.pins; logged in Change history, so Undo works). */
const Pins = {
  get() { const p = (App.info.ui || {}).pins; return Array.isArray(p) ? p : [...(window.DEFAULT_PINS || [])]; },
  has(id) { return Pins.get().includes(id); },
  async toggle(id) {
    let p = Pins.get();
    if (p.includes(id)) p = p.filter(x => x !== id);
    else if (p.length >= (window.MAX_PINS || 4)) { toast(`Home shows up to ${window.MAX_PINS || 4} tools. Unpin one first (tap its star).`, true); return false; }
    else p = [...p, id];
    (App.info.ui ||= {}).pins = p;
    try { await App.api.ui_set({ pins: p }); } catch { /* preview */ }
    return true;
  },
};

function toolTile(f, { onPin } = {}) {
  const S = isSimple(), adv = S && f.simple.link, t = f.tile;
  const pinned = Pins.has(f.id);
  const star = h("button.tile-star" + (pinned ? ".on" : ""), { title: pinned ? "Remove from Home" : "Add to Home", "aria-pressed": pinned,
    "aria-label": (pinned ? "Unpin " : "Pin ") + t.short + (pinned ? " from Home" : " to Home"),
    onclick: async (e) => { e.stopPropagation(); if (await Pins.toggle(f.id)) { if (onPin) onPin(); else star.replaceWith(toolTile(f).querySelector(".tile-star")); } } }, icon("star"));
  return h("div.tile" + (adv ? ".tile-adv" : ""), { role: "button", tabIndex: 0, "data-tool": f.id, title: adv ? "An advanced feature - opens in Advanced view" : t.desc,
    onclick: () => openFeature(f), onkeydown: (e) => { if (e.key === "Enter") openFeature(f); } },
    star, h("div.tile-icon", icon(t.icon)), h("div.tile-name", t.short), h("div.tile-desc", t.desc),
    adv ? h("div.tile-adv-tag", "Advanced view →") : null);
}

App.pages.tools = {
  render(el) {
    this.el = el;
    const S = isSimple(), F = (window.FEATURES || []).filter(f => f.tile);
    el.append(plainHead("Tools", "Everything RigLab can do. Tap a tool to open it. Tap the star to put it on Home.",
      "Tools", "Every tool. The star pins it to Home (up to 4)."));
    const everyday = F.filter(f => !f.simple.link), advanced = F.filter(f => f.simple.link);
    const draw = () => this.grid.replaceChildren(
      h("div.tile-grid", everyday.map(f => toolTile(f, { onPin: draw }))),
      h("h2.home-h2.mt", S ? "Advanced tools" : "More tools"),
      S ? h("div.small.muted", { style: { margin: "-4px 0 12px" } }, "These are more technical, so they open in Advanced view. You can switch back any time.") : null,
      h("div.tile-grid", advanced.map(f => toolTile(f, { onPin: draw }))));
    this.grid = h("div");
    el.append(this.grid);
    draw();
  },
};

// =================================================================== Themes
App.pages.themes = {
  render(el) {
    el.append(plainHead("Themes", "Pick how RigLab looks. Changes apply straight away and are saved. Green, yellow and red stay easy to read in every theme.",
      "Themes", "Colour palettes and highlight colour. Applies instantly (ui.theme / ui.accent). Licences are in Settings → About."));
    const box = h("div");
    const ui = () => (App.info.ui ||= {});
    const draw = () => {
      const cur = Theme.cur;
      box.replaceChildren(
        h("div.card", cardHead("Theme", "palette"),
          h("div.theme-grid", THEMES.map(([id, name]) => {
            const pvTheme = id === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : id;
            return h("button.theme-card" + (cur.theme === id ? ".on" : ""), { "aria-pressed": cur.theme === id, title: name, "data-theme-id": id,
              onclick: () => { ui().theme = id; ui().accent = "theme"; Theme.set({ theme: id, accent: "theme" }); } },
              h("div.theme-pv", { "data-theme": pvTheme }, h("div.side"), h("div.main", h("div.ln"), h("div.ln.m"),
                h("div.dots", h("i", { style: { background: "var(--good)" } }), h("i", { style: { background: "var(--warn)" } }), h("i", { style: { background: "var(--bad)" } }),
                  h("i", { style: { background: "var(--accent)", marginLeft: "auto" } })))),
              h("div.theme-name", { "data-theme": pvTheme }, name, cur.theme === id ? " ✓" : ""));
          }))),
        h("div.card.mt", cardHead("Highlight colour", "sliders"), h("div.sub", "The colour for buttons, links and selected items. 'Theme's own' uses the theme's colour."),
          h("div.row.wrap", { style: { gap: "12px" } }, Object.entries(THEME_ACCENTS).map(([k, l]) => {
            const pal = { theme: ["var(--accent)", "var(--accent-2)"], cyan: ["#36d6ff", "#8f6bff"], violet: ["#a37bff", "#ff5fb8"], emerald: ["#2fe0a0", "#2fb5ff"], amber: ["#ffb636", "#ff6b3d"], crimson: ["#ff4d6d", "#ff9a3d"], ocean: ["#4d8dff", "#36d6ff"], mono: ["#c7cedb", "#7d8799"] }[k];
            const on = (cur.accent || "theme") === k;
            return h("div", { style: { textAlign: "center" } }, h("div.theme-swatch" + (on ? ".on" : ""), { role: "button", tabIndex: 0, title: l, "aria-label": l + " highlight colour", "aria-pressed": on,
              style: { background: k === "theme" ? `linear-gradient(135deg, ${pal[0]} 50%, ${pal[1]} 50%)` : `linear-gradient(135deg, ${pal[0]}, ${pal[1]})` },
              onclick: () => { ui().accent = k; Theme.set({ accent: k }); } }), h("div.small.muted", { style: { marginTop: "4px" } }, k === "theme" ? "Theme's own" : l));
          }))),
        h("div.card.mt", cardHead("How the status colours look in this theme", "info"), colourKey({ risk: true, label: "Show the colour and risk key" }),
          h("div.small.muted", { style: { marginTop: "8px" } }, "Theme palettes are used under the MIT licence. Credits are in Settings → About.")));
    };
    draw();
    el.append(box);
  },
};
