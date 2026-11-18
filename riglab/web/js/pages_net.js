/* Tools -> Speed Test (3.12 redesign): a big speedometer (the shared Gauge) with a GO button in the middle.
   Ping first, then download, then upload - the live speed is big in the centre and each finished result lands in
   the row above the gauge. ISP, server and connection sit small underneath (full details in Advanced view),
   then past results. Uses Cloudflare's speed test servers (see riglab/core/netspeed.py for why). */
"use strict";

const NET_LIGHT = { download: { warn: 25, bad: 5, low: true }, upload: { warn: 5, bad: 1, low: true }, ping: { warn: 60, bad: 120 }, jitter: { warn: 20, bad: 50 }, loss: { warn: 0.5, bad: 3 } };
function netLight(k, v) {
  const t = NET_LIGHT[k];
  if (v == null || !t) return "none";
  return t.low ? (v < t.bad ? "bad" : v < t.warn ? "warn" : "good") : (v >= t.bad ? "bad" : v >= t.warn ? "warn" : "good");
}
const NET_WORDS = {
  ping: ["Ping", "ms", "How long a message takes to get there and back. Lower is better for games."],
  jitter: ["Jitter", "ms", "How much the ping jumps around. Lower means smoother games and calls."],
  download: ["Download", "Mbps", "How fast things arrive: videos, games, web pages."],
  upload: ["Upload", "Mbps", "How fast you send things: video calls, streaming yourself, backups."],
  loss: ["Packet loss", "%", "Data that never arrived. Anything above 0 can make games stutter."],
};
const SPEED_TICKS = [0, 5, 10, 25, 50, 100, 250, 500, 1000];
/* the dial's scale: each tick is the same distance apart (like a classic speedometer), straight lines between */
function speedFrac(v) {
  if (!(v > 0)) return 0;
  const T = SPEED_TICKS, n = T.length - 1;
  for (let i = 1; i <= n; i++) if (v <= T[i]) return (i - 1 + (v - T[i - 1]) / (T[i] - T[i - 1])) / n;
  return 1;
}
function fmtNet(k, v) {
  if (v == null || !Number.isFinite(+v)) return "—";
  if (k === "download" || k === "upload") return v >= 100 ? String(Math.round(v)) : (+v).toFixed(1);
  if (k === "loss") return (+v).toFixed(v < 1 && v > 0 ? 1 : 0);
  return String(Math.round(v));
}
const netWhen = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

App.pages.netspeed = {
  render(el) {
    this.el = el;
    el.append(plainHead("Speed Test", "How fast is your internet, and what is it good enough for?",
      "Internet speed test", "Cloudflare speed test servers: multi-stream download/upload (8 s each), ping, jitter and loss via ICMP to 1.1.1.1."));
    this.g = Gauge.create({ kind: "arc", size: 300, stops: null, scale: speedFrac, ticks: SPEED_TICKS, needle: true, unit: "Mbps", label: "Speed",
      format: (v) => (v >= 100 ? String(Math.round(v)) : (+v).toFixed(1)), duration: 1100 });
    this.row = h("div.speed-row");
    this.under = h("div.speed-under");
    this.info = h("div.speed-info");
    this.more = h("div");
    this.hist = h("div.card.mt");
    el.append(h("div.card.speed-stage", this.row, h("div.speed-gauge", this.g.el), this.under, this.info, this.more), this.hist);
    this.drawRow({});
    this.showGo();
    this.load();
  },
  leave() { clearTimeout(this.t); if (this.g) this.g.destroy(); },
  goButton(label = "GO") {
    return h("button.speed-go", { "aria-label": label === "GO" ? "Start the speed test" : label, "data-speed": "go", onclick: () => this.start() }, label);
  },
  showGo() {
    this.g.set(null);
    this.g.setCenter(this.goButton());
    this.under.replaceChildren(h("div.small.muted", this.note || "A test uses some internet data: up to about 300 MB on a fast connection, much less on a slow one."));
  },
  async load() {
    let st, hist;
    try { [st, hist] = await Promise.all([App.api.netspeed_status(), App.api.netspeed_history()]); } catch { return; }
    if (!document.body.contains(this.el)) return;
    this.history = (hist && hist.items) || [];
    this.note = hist && hist.note;
    if (st && st.running) { this.running(st); this.poll(); }
    else if (st && st.result) this.done(st.result, false);
    else if (this.history.length) this.done(this.history[0], true);
    else this.showGo();
    this.drawHistory();
  },
  async start() {
    this.drawRow({});
    this.info.replaceChildren();
    this.more.replaceChildren();
    let st;
    try { st = await App.api.netspeed_start(); } catch (e) { toast("Couldn't start the test: " + e, true); return; }
    this.running(st || {});
    this.poll();
  },
  poll() {
    clearTimeout(this.t);
    this.t = setTimeout(async () => {
      if (!document.body.contains(this.el)) return;
      let st;
      try { st = await App.api.netspeed_status(); } catch { st = null; }
      if (!st) return this.poll();
      if (st.running) { this.running(st); return this.poll(); }
      if (st.cancelled) { this.showGo(); this.drawRow({}); this.under.prepend(h("div.small.muted", "Test cancelled. Nothing was saved.")); return; }
      if (st.result) {
        this.done(st.result, false);
        try { const hh = await App.api.netspeed_history(); this.history = hh.items || []; } catch { /* keep */ }
        this.drawHistory();
      }
    }, 250);
  },
  running(st) {
    const p = st.partial || {}, live = p.live || {}, phase = live.phase || st.phase || "ping";
    this.drawRow(p, phase);
    this.g.setCenter(null);
    if (phase === "download" || phase === "upload") {
      this.g.scan(false);
      this.g.setUnit("Mbps").setSub(phase === "download" ? "↓ Download" : "↑ Upload");
      this.g.follow(live.mbps ?? 0);
    } else {
      this.g.scan(true, st.progress || 0);                   // connecting and measuring ping: the scanning glow
      this.g.setUnit("").setSub(st.step || "Starting…");
    }
    this.under.replaceChildren(h("div.row", { style: { gap: "12px", justifyContent: "center" } },
      h("span.small.muted", st.step || "Starting…"),
      h("button.btn.sm", { onclick: () => App.api.netspeed_cancel() }, icon("stop"), "Cancel")));
  },
  done(r, old) {
    this.g.scan(false);
    if (!r || r.offline) {
      this.g.set(null);
      this.g.setCenter(this.goButton("Try again"));
      this.drawRow({});
      this.under.replaceChildren(banner("bad", "alert", "<b>No internet connection.</b> Connect to Wi-Fi or plug in a network cable, then press Try again."));
      this.info.replaceChildren();
      this.more.replaceChildren();
      return;
    }
    this.drawRow(r, null, true);
    if (old) { this.g.set(null); this.g.setCenter(this.goButton()); }          // opening the page: GO first, last result in the row
    else { this.g.setCenter(null).setUnit("Mbps").setSub("↓ Download"); this.g.set(r.download ?? null); }
    const sum = r.summary || {};
    this.under.replaceChildren(
      r.error ? banner("info", "info", safe(r.error)) : h("div.speed-say", dot(sum.state || "none"), h("span", safe(sum.say, ""))),
      h("div.row", { style: { gap: "10px", justifyContent: "center", marginTop: "10px" } },
        old ? null : h("button.btn.primary", { "data-speed": "again", onclick: () => this.start() }, icon("refresh"), "Test again"),
        h("span.small.muted", (old ? "Last test " : "Tested ") + netWhen(r.time)), colourKey({ grey: false })));
    const c = r.conn || {};
    const conn = !c.type ? "Connection unknown" : c.type === "Wi-Fi"
      ? `Wi-Fi${c.band ? " · " + c.band : ""}${c.signal != null ? ` · signal ${c.signal}%${c.signal_words ? " (" + c.signal_words + ")" : ""}` : ""}` : "Ethernet (cable)";
    const ipBox = h("span", "IP hidden ", h("button.btn.sm.ghost", { "data-speed": "show-ip", onclick: () => ipBox.replaceChildren(h("span.mono", safe(r.ip, "unknown"))) }, "Show"));
    this.info.replaceChildren(
      h("span", icon("home"), safe(r.isp, "Internet provider unknown")), h("span", icon("link"), safe(r.server, "Cloudflare")), h("span", icon("net"), conn), ipBox);
    if (isSimple()) { this.more.replaceChildren(); return; }
    this.more.replaceChildren(details("Full details",
      h("div.spec", h("div.k", "Download"), h("div.v", `${fmtNet("download", r.download)} Mbps`), h("div.k", "Upload"), h("div.v", `${fmtNet("upload", r.upload)} Mbps`),
        h("div.k", "Ping"), h("div.v", `${fmtNet("ping", r.ping)} ms`), h("div.k", "Jitter"), h("div.v", `${fmtNet("jitter", r.jitter)} ms`),
        h("div.k", "Packet loss"), h("div.v", r.loss == null ? "Not measured (ping blocked on this network)" : `${fmtNet("loss", r.loss)} %`),
        h("div.k", "Test server"), h("div.v", safe(r.server)), h("div.k", "Internet provider"), h("div.v", safe(r.isp)),
        h("div.k", "Connection"), h("div.v", safe(c.type, "Unknown")), h("div.k", "Adapter"), h("div.v", safe(c.adapter)),
        h("div.k", "Link speed"), h("div.v", safe(c.link)),
        c.type === "Wi-Fi" ? [h("div.k", "Wi-Fi band"), h("div.v", safe(c.band)), h("div.k", "Wi-Fi standard"), h("div.v", safe(c.radio)), h("div.k", "Signal"), h("div.v", c.signal != null ? c.signal + "%" : "—")] : null,
        h("div.k", "Data used"), h("div.v", r.data_mb != null ? `${r.data_mb} MB` : "—")),
      h("div.small.muted", { style: { marginTop: "6px" } }, "Speed test by Cloudflare (speed.cloudflare.com). Ping, jitter and packet loss measured with Windows' ping to 1.1.1.1.")));
  },
  drawRow(p, phase, final) {
    const items = ["ping", "jitter", "download", "upload"].map(k => {
      const v = p[k], active = phase === k || (phase === "ping" && k === "jitter");
      const st = final ? netLight(k, v) : "none";
      return h("div.speed-item" + (active ? ".active" : "") + (v != null ? ".has" : ""), { "data-metric": k },
        h("div.speed-k", final && v != null ? dot(st) : null, k === "download" ? "↓ " : k === "upload" ? "↑ " : "", NET_WORDS[k][0]),
        h("div.speed-v", fmtNet(k, v), h("small", " " + NET_WORDS[k][1])),
        isSimple() && final ? h("div.speed-d", NET_WORDS[k][2]) : null);
    });
    this.row.replaceChildren(...items);
  },
  drawHistory() {
    const H = this.history || [];
    const c = h("canvas.chart", { style: { height: "140px" } });
    this.hist.replaceChildren(cardHead("Past tests", "clock"),
      H.length < 2 ? null : c,
      H.length < 2 ? null : h("div.row.small.muted", { style: { gap: "16px", margin: "4px 0 10px" } },
        h("span", h("b", { style: { color: css("--accent") } }, "━ "), "Download"), h("span", h("b", { style: { color: css("--muted") } }, "━ "), "Upload")),
      H.length ? h("div.stack", { style: { gap: "4px" } }, H.slice(0, 8).map(x => h("div.hist-mini",
        h("span.small.muted", netWhen(x.time)),
        h("span", `↓ ${fmtNet("download", x.download)} Mbps`), h("span", `↑ ${fmtNet("upload", x.upload)} Mbps`), h("span", `${fmtNet("ping", x.ping)} ms`),
        h("span.small.muted", safe((x.conn || {}).type, "")))))
        : h("div.small.muted", "Your results are saved here so you can compare them."));
    if (H.length >= 2) requestAnimationFrame(() => {
      const pts = [...H].reverse().map((x, i) => [i + 1, x.download || 0]), up = [...H].reverse().map((x, i) => [i + 1, x.upload || 0]);
      drawChart(c, [{ data: pts, color: css("--accent") }, { data: up, color: css("--muted") }], { yMin: 0, xLabel: "test", yLabel: "Mbps" });
    });
  },
};
