/* Internet speed test (Tools). Uses Cloudflare's speed test servers; see riglab/core/netspeed.py. */
"use strict";

const NET_LIGHT = { download: { warn: 25, bad: 5, low: true }, upload: { warn: 5, bad: 1, low: true }, ping: { warn: 60, bad: 120 }, jitter: { warn: 20, bad: 50 }, loss: { warn: 0.5, bad: 3 } };
function netLight(k, v) {
  const t = NET_LIGHT[k];
  if (v == null || !t) return "none";
  return t.low ? (v < t.bad ? "bad" : v < t.warn ? "warn" : "good") : (v >= t.bad ? "bad" : v >= t.warn ? "warn" : "good");
}
const NET_WORDS = {
  download: ["Download", "Mbps", "How fast things arrive: videos, games, web pages."],
  upload: ["Upload", "Mbps", "How fast you send things: video calls, streaming yourself, backups."],
  ping: ["Ping", "ms", "How long a message takes to get there and back. Lower is better for games."],
  jitter: ["Jitter", "ms", "How much the ping jumps around. Lower means smoother games and calls."],
  loss: ["Packet loss", "%", "Data that never arrived. Anything above 0 can make games stutter."],
};

App.pages.netspeed = {
  render(el) {
    this.el = el;
    el.append(plainHead("Internet speed", "Test how fast your internet is, and what it's good enough for.",
      "Network speed test", "Download/upload via Cloudflare's speed test servers (multi-stream, 8 s each); ping, jitter and loss via ICMP to 1.1.1.1."));
    this.top = h("div.card");
    this.res = h("div");
    this.hist = h("div.card.mt");
    el.append(this.top, this.res, this.hist);
    this.drawIdle();
    this.load();
  },
  async load() {
    let st, hist;
    try { [st, hist] = await Promise.all([App.api.netspeed_status(), App.api.netspeed_history()]); } catch { return; }
    if (!document.body.contains(this.el)) return;
    this.history = hist.items || [];
    this.note = hist.note;
    if (st.running) { this.drawRunning(st); this.poll(); }
    else if (st.result) this.drawResult(st.result);
    else if (this.history.length) this.drawResult(this.history[0], true);
    this.drawIdle(st.running);
    this.drawHistory();
  },
  drawIdle(running) {
    this.top.replaceChildren(cardHead(isSimple() ? "Test my internet" : "Run a test", "net"),
      h("div.sub", this.note || "A test uses some internet data: up to about 300 MB on a fast connection, much less on a slow one."),
      running ? h("div.small.muted", "A test is running…")
        : h("div.row.wrap", { style: { gap: "10px" } }, actionBtn("netspeed.start", () => this.start(), { cls: "primary", icon: "play", always: true }),
          h("span.small.muted", "Takes about 40 seconds. Close downloads and video for the most accurate result.")));
  },
  async start() {
    const st = await App.api.netspeed_start();
    this.drawIdle(true);
    this.drawRunning(st);
    this.poll();
  },
  poll() {
    clearTimeout(this.t);
    this.t = setTimeout(async () => {
      if (!document.body.contains(this.el)) return;
      const st = await App.api.netspeed_status();
      if (st.running) { this.drawRunning(st); return this.poll(); }
      this.drawIdle(false);
      if (st.cancelled) { this.res.replaceChildren(h("div.card.mt", h("div.small.muted", "Test cancelled. Nothing was saved."))); return; }
      if (st.result) { this.drawResult(st.result); const hh = await App.api.netspeed_history(); this.history = hh.items || []; this.drawHistory(); }
    }, 700);
  },
  drawRunning(st) {
    const p = st.partial || {};
    const live = Object.keys(NET_WORDS).filter(k => p[k] != null).map(k => h("div.net-tile", h("div.small.muted", NET_WORDS[k][0]), h("div.stat-big", fmtNet(k, p[k]), h("small", " " + NET_WORDS[k][1]))));
    this.res.replaceChildren(h("div.card.mt", cardHead("Testing…", "net"),
      h("div.small", (st.step || "Starting…") + (st.count ? ` (step ${st.index} of ${st.count})` : "")),
      h("div.bar", { style: { margin: "10px 0" } }, h("i", { style: { width: Math.round((st.progress || 0) * 100) + "%" } })),
      h("div.row", h("span.small.muted", st.eta_text || ""), h("div.spacer"), h("button.btn.sm", { onclick: () => App.api.netspeed_cancel() }, icon("stop"), "Cancel")),
      live.length ? h("div.net-tiles.mt", live) : null));
  },
  drawResult(r, old) {
    const S = isSimple();
    if (r.offline) {
      this.res.replaceChildren(h("div.mt", banner("bad", "alert", "<b>No internet connection.</b> Connect to Wi-Fi or plug in a network cable, then try again.")));
      return;
    }
    const sum = r.summary || {};
    const tiles = Object.keys(NET_WORDS).map(k => {
      const st = netLight(k, r[k]);
      return h("div.net-tile", h("div.row", { style: { gap: "8px" } }, dot(st, (XD.legend || {})[st]), h("span.small.muted", NET_WORDS[k][0])),
        h("div.stat-big", r[k] == null ? "—" : fmtNet(k, r[k]), h("small", " " + NET_WORDS[k][1])),
        S ? h("div.small.muted", NET_WORDS[k][2]) : null);
    });
    const c = r.conn || {};
    const connLine = !c.type ? "RigLab couldn't tell how you're connected."
      : c.type === "Wi-Fi" ? `Wi-Fi${c.band ? ` on ${c.band}` : ""}${c.signal != null ? `, signal ${c.signal}% (${c.signal_words})` : ""}${c.link ? `, link ${c.link}` : ""}.`
        : `Ethernet (network cable)${c.link ? `, link ${c.link}` : ""}.`;
    const ipBox = h("span", "Hidden ", h("button.btn.sm.ghost", { onclick: () => ipBox.replaceChildren(h("span.mono", r.ip || "unknown")) }, "Show"));
    this.res.replaceChildren(h("div.card.mt",
      cardHead(old ? "Last result" : "Result", "net", h("span.small.muted", new Date(r.time * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }))),
      r.error ? banner("info", "info", r.error) : h("div.row", { style: { gap: "10px", fontSize: "17px", fontWeight: 600, margin: "4px 0 14px" } }, dot(sum.state || "none"), h("span", sum.say || "")),
      h("div.net-tiles", tiles),
      h("div.spec.mt", h("div.k", "Connection"), h("div.v", connLine),
        h("div.k", "Test server"), h("div.v", r.server || "—"), h("div.k", "Internet provider"), h("div.v", r.isp || "—"),
        h("div.k", "Public IP address"), h("div.v", ipBox),
        S ? null : h("div.k", "Data used"), S ? null : h("div.v", r.data_mb != null ? `${r.data_mb} MB` : "—"),
        S ? null : h("div.k", "Adapter"), S ? null : h("div.v", c.adapter || "—"), S || c.type !== "Wi-Fi" ? null : h("div.k", "Wi-Fi standard"), S || c.type !== "Wi-Fi" ? null : h("div.v", c.radio || "—")),
      h("div.mt", colourKey({ grey: false })),
      h("div.small.muted", { style: { marginTop: "6px" } }, "Speed test by Cloudflare (speed.cloudflare.com). Ping, jitter and packet loss measured with Windows' ping to 1.1.1.1.")));
  },
  drawHistory() {
    const H = this.history || [];
    const c = h("canvas.chart", { style: { height: "150px" } });
    this.hist.replaceChildren(cardHead("Past tests", "clock"),
      H.length < 2 ? null : c,
      H.length < 2 ? null : h("div.row.small.muted", { style: { gap: "16px", margin: "4px 0 10px" } },
        h("span", h("b", { style: { color: css("--accent") } }, "━ "), "Download"), h("span", h("b", { style: { color: css("--accent-2") } }, "━ "), "Upload")),
      H.length ? h("div.stack", { style: { gap: "4px" } }, H.slice(0, 10).map(x => h("div.hist-mini",
        h("span.small.muted", new Date(x.time * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })),
        h("span", `↓ ${fmtNet("download", x.download)} Mbps`), h("span", `↑ ${fmtNet("upload", x.upload)} Mbps`), h("span", `${fmtNet("ping", x.ping)} ms`),
        h("span.small.muted", (x.conn || {}).type || ""))))
        : h("div.small.muted", "Your results are saved here so you can compare them."));
    if (H.length >= 2) requestAnimationFrame(() => {
      const pts = [...H].reverse().map((x, i) => [i + 1, x.download || 0]), up = [...H].reverse().map((x, i) => [i + 1, x.upload || 0]);
      drawChart(c, [{ data: pts, color: css("--accent") }, { data: up, color: css("--accent-2") }], { yMin: 0, xLabel: "test", yLabel: "Mbps" });
    });
  },
};

function fmtNet(k, v) {
  if (v == null) return "—";
  if (k === "download" || k === "upload") return v >= 100 ? Math.round(v) : v.toFixed(1);
  if (k === "loss") return (+v).toFixed(v < 1 && v > 0 ? 1 : 0);
  return Math.round(v);
}
