/* Change history: everything RigLab changed on this PC, newest first, with Undo where it can be undone. */
"use strict";

const HIST_SOURCE = { you: "You", fix: "Fix it button", undo: "Undo", auto: "RigLab, for safety" };

App.pages.history = {
  render(el) {
    this.el = el;
    el.append(pageHead("Change history", isSimple()
      ? "Everything RigLab has changed on your PC, newest first. Press Undo to put something back the way it was."
      : "Every change RigLab applied, with what it was before. Undo restores the previous value and is logged too.",
      h("button.btn", { onclick: () => this.load() }, icon("refresh"), "Refresh")));
    this.box = h("div.card", h("div.empty", h("div.spinner")));
    const L = (state, txt) => h("div.key-row", dot(state), txt);
    el.append(h("details.key", { style: { margin: "-8px 0 12px" } }, h("summary", "What do the colours mean?"), h("div.key-body",
      L("good", "Done - a None or Low risk change"), L("warn", "Done - a Medium or High risk change (RigLab checked for a restore point first)"),
      L("bad", "Didn't work - nothing was changed, or only part of it"), L("none", "An undo, putting something back"),
      h("div.key-sep"), h("div.key-row", h("span.pill", "Undone"), "This change has already been undone"))));
    el.append(this.box, h("div.small.muted.mt", "Some things can't be undone, like deleted temporary files or a restore point. They're still listed so you can see what happened."));
    this.load();
  },
  async load() {
    let list = [];
    try { list = await App.api.changes_list(); } catch (e) { toast("Couldn't read the change history: " + e, true); }
    if (!document.body.contains(this.el)) return;
    if (!list.length) {
      this.box.replaceChildren(h("div.empty", icon("undo"), h("div.mt", "Nothing changed yet."),
        h("div.small.muted", "When RigLab changes a setting, it shows up here with an Undo button.")));
      return;
    }
    const day = (t) => new Date(t * 1000).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
    const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const rows = [];
    let last = null;
    for (const e of list) {
      const d = day(e.time);
      if (d !== last) { rows.push(h("div.nav-label", { style: { padding: "14px 0 2px" } }, d)); last = d; }
      const state = !e.ok ? "bad" : e.source === "undo" ? "none" : ["Medium", "High"].includes(e.risk) ? "warn" : "good";
      let right;
      if (e.undoable) {
        right = actionBtn("change.undo", async () => {
          const r = await App.api.change_undo(e.id);
          toast(r.msg, !r.ok);
          this.load();
        }, { cls: "sm", icon: "undo", label: "Undo", always: true });
      } else if (e.undone_by) right = h("span.pill", "Undone");
      else right = h("span.small.muted", e.source === "undo" ? "" : "Can't be undone");
      rows.push(h("div.hist-row" + (e.undone_by ? ".undone" : ""), dot(state, e.ok ? "" : "This change didn't work"),
        h("div", { style: { minWidth: 0 } },
          h("div.hist-title", e.title, e.ok ? null : h("span.pill.bad", { style: { marginLeft: "8px" } }, "didn't work")),
          h("div.small.muted", `${clock(e.time)} · ${HIST_SOURCE[e.source] || e.source}` + (e.risk && e.risk !== "None" && e.risk !== "Low" ? ` · ${e.risk} risk` : "") + (e.detail ? ` · ${e.detail}` : ""))),
        right));
    }
    this.box.replaceChildren(...rows);
  },
};
