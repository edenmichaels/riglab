/* Preview mode: a fake backend with realistic numbers, used when the page is opened in a normal
   browser (no Python). Lets you click through and tweak the design without running RigLab. */
"use strict";

class DemoApi {
  constructor() {
    this.t0 = Date.now();
    this.hist = {};
    this.curves = {};
    this.fanOn = true;
    this.bench = { running: false, msg: "", progress: 0, results: [], error: null };
    this.stress = null;
    this.gpuRes = null;
    this.cfg = { alerts: { enabled: true, cpu_temp_max: 90, gpu_temp_max: 85, drive_temp_max: 65, cooldown_seconds: 120 },
      overlay: { enabled: false, corner: "top-left", opacity: 0.85, show_fps: false, mode: "full", size: "m", fps_color: "auto", x: null, y: null }, logging: { enabled: false, interval_s: 5 },
      openrgb: { host: "127.0.0.1", port: 6742 }, minimize_to_tray: true, start_minimized: false, poll_interval_ms: 1000 };
    this.defs = this.makeDefs();
    for (let i = 0; i < 120; i++) this.sample(-120 + i);
  }
  makeDefs() {
    const C = "AMD Ryzen 7 7800X3D", G = "NVIDIA GeForce RTX 4070 SUPER", M = "ASUS TUF GAMING B650-PLUS WIFI › Nuvoton NCT6799D",
      X = "Corsair Commander Core XT", S = "Samsung SSD 990 PRO 2TB", R = "Generic Memory";
    const d = [];
    const add = (id, hw, type, kind, name, base, amp, unit, extra = {}) => d.push({ id, hw, type, kind, name, base, amp, unit, ...extra });
    add("/amdcpu/0/temperature/2", C, "Cpu", "Temperature", "Core (Tctl/Tdie)", 58, 9, "°C");
    add("/amdcpu/0/temperature/3", C, "Cpu", "Temperature", "CCD1 (Tdie)", 55, 8, "°C");
    add("/amdcpu/0/load/0", C, "Cpu", "Load", "CPU Total", 24, 18, "%");
    for (let i = 1; i <= 8; i++) add(`/amdcpu/0/load/${i}`, C, "Cpu", "Load", `CPU Core #${i}`, 22, 22, "%");
    for (let i = 1; i <= 8; i++) add(`/amdcpu/0/clock/${i}`, C, "Cpu", "Clock", `Core #${i}`, 4700, 250, "MHz");
    add("/amdcpu/0/power/0", C, "Cpu", "Power", "Package", 48, 22, "W");
    add("/amdcpu/0/voltage/0", C, "Cpu", "Voltage", "Core (SVI2 TFN)", 1.12, 0.06, "V");
    add("/gpu-nvidia/0/temperature/0", G, "GpuNvidia", "Temperature", "GPU Core", 52, 10, "°C");
    add("/gpu-nvidia/0/temperature/2", G, "GpuNvidia", "Temperature", "GPU Hot Spot", 63, 11, "°C");
    add("/gpu-nvidia/0/load/0", G, "GpuNvidia", "Load", "GPU Core", 35, 30, "%");
    add("/gpu-nvidia/0/clock/0", G, "GpuNvidia", "Clock", "GPU Core", 2450, 300, "MHz");
    add("/gpu-nvidia/0/power/0", G, "GpuNvidia", "Power", "GPU Package", 95, 70, "W");
    add("/gpu-nvidia/0/fan/0", G, "GpuNvidia", "Fan", "GPU Fan 1", 1200, 300, "RPM");
    add("/ram/load/0", R, "Memory", "Load", "Memory", 46, 4, "%");
    add("/ram/data/0", R, "Memory", "Data", "Memory Used", 14.6, 1.2, "GB");
    add("/lpc/nct6799d/temperature/0", M, "SuperIO", "Temperature", "Motherboard", 38, 2, "°C");
    add("/lpc/nct6799d/temperature/1", M, "SuperIO", "Temperature", "CPU Socket", 44, 3, "°C");
    add("/lpc/nct6799d/fan/0", M, "SuperIO", "Fan", "CPU Fan", 1150, 120, "RPM");
    add("/lpc/nct6799d/fan/1", M, "SuperIO", "Fan", "Chassis Fan #1", 860, 60, "RPM");
    add("/lpc/nct6799d/control/0", M, "SuperIO", "Control", "CPU Fan", 45, 6, "%", { ctrl: true });
    add("/lpc/nct6799d/control/1", M, "SuperIO", "Control", "Chassis Fan #1", 38, 4, "%", { ctrl: true });
    for (let i = 1; i <= 3; i++) {
      add(`/liquidctl/0/rpm/fan${i}`, X, "Controller", "Fan", `Fan speed ${i}`, 1020 + i * 15, 70, "RPM");
      add(`/liquidctl/0/control/fan${i}`, X, "Controller", "Control", `Fan ${i}`, 50, 0, "%", { ctrl: true });
    }
    add("/liquidctl/0/temp/temperature_1", X, "Controller", "Temperature", "Temperature 1", 31, 1, "°C");
    add("/nvme/0/temperature/0", S, "Storage", "Temperature", "Composite Temperature", 41, 3, "°C");
    add("/nvme/0/load/0", S, "Storage", "Load", "Used Space", 61, 0, "%");
    add("/ps/ram/used", "Memory", "Memory", "Data", "Memory Used", 14.6, 1, "GB");
    add("/ps/ram/avail", "Memory", "Memory", "Data", "Memory Available", 17.1, 1, "GB");
    add("/ps/disk/read", "Disks (all)", "Storage", "Throughput", "Read", 2.5e6, 2.4e6, "B/s");
    add("/ps/disk/write", "Disks (all)", "Storage", "Throughput", "Write", 1.1e6, 1.0e6, "B/s");
    add("/ps/net/down", "Network", "Network", "Throughput", "Download", 3.2e6, 3e6, "B/s");
    add("/ps/net/up", "Network", "Network", "Throughput", "Upload", 2.4e5, 2e5, "B/s");
    return d;
  }
  load() { // fake "game" load cycle
    const t = (Date.now() - this.t0) / 1000;
    let x = 0.5 + 0.5 * Math.sin(t / 23) * Math.sin(t / 7.3);
    if (this.stress && this.stress.running) x = 1;
    return x;
  }
  val(d, t) {
    const L = this.load(), n = Math.sin(t * 1.7 + d.id.length) * 0.3 + Math.sin(t * 0.37 + d.base) * 0.4 + (Math.random() - .5) * .3;
    if (d.ctrl && d.id.startsWith("/liquidctl") && this.curves[d.id]) return this.curves[d.id].applied;
    let v = d.base + d.amp * ((L - 0.5) * 1.6 + n * 0.6);
    if (d.kind === "Load" || d.kind === "Control") v = Math.max(0, Math.min(100, v));
    if (d.kind === "Throughput") v = Math.max(0, d.base * (0.2 + Math.random() * 1.6));
    return d.kind === "Voltage" ? +v.toFixed(3) : +v.toFixed(2);
  }
  sample(rel) {
    const t = (Date.now() - this.t0) / 1000 + rel;
    for (const d of this.defs) {
      const v = this.val(d, t);
      d.value = v; d.min = Math.min(d.min ?? v, v); d.max = Math.max(d.max ?? v, v);
      (this.hist[d.id] ||= []).push([Date.now() / 1000 + rel, v]);
      if (this.hist[d.id].length > 300) this.hist[d.id].shift();
    }
  }
  f(d, v) {
    if (v == null) return "—";
    if (d.kind === "Throughput") return fmt.rate(v);
    if (d.kind === "Fan" || d.kind === "Clock") return fmt.n(v, 0) + " " + d.unit;
    if (d.kind === "Voltage") return v.toFixed(3) + " V";
    return v.toFixed(1) + " " + d.unit;
  }
  // ------------------------------------------------------------ api
  async info() { return { ui: this.uiCfg || {}, version: "3.7.0", admin: true, platform: "win32", demo: true, status: this.status() }; }
  status() { return { "LibreHardwareMonitor": "active", "liquidctl (fan hubs / AIOs)": "active", "NVIDIA NVML": "active", psutil: "active" }; }
  async snapshot() {
    this.sample(0);
    const by = (id) => this.defs.find(d => d.id === id);
    const v = (id) => by(id)?.value ?? null;
    const sensors = this.defs.map(d => ({ id: d.id, hw: d.hw, type: d.type, kind: d.kind, name: d.name, value: d.value, min: d.min, max: d.max,
      unit: d.unit, fmt: this.f(d, d.value), fmin: this.f(d, d.min), fmax: this.f(d, d.max), ctrl: !!d.ctrl }));
    const clocks = this.defs.filter(d => d.type === "Cpu" && d.kind === "Clock").map(d => d.value);
    return { t: Date.now() / 1000, sensors, status: this.status(), summary: {
      cpu_temp: v("/amdcpu/0/temperature/2"), cpu_load: v("/amdcpu/0/load/0"), cpu_power: v("/amdcpu/0/power/0"),
      gpu_temp: v("/gpu-nvidia/0/temperature/0"), gpu_load: v("/gpu-nvidia/0/load/0"), gpu_power: v("/gpu-nvidia/0/power/0"),
      ram_load: v("/ram/load/0"), cpu_clock: clocks.reduce((a, b) => a + b, 0) / clocks.length,
      ram_used: v("/ps/ram/used"), ram_avail: v("/ps/ram/avail"), disk_r: v("/ps/disk/read"), disk_w: v("/ps/disk/write"),
      net_d: v("/ps/net/down"), net_u: v("/ps/net/up"),
      ids: { cpu_temp: "/amdcpu/0/temperature/2", cpu_load: "/amdcpu/0/load/0", cpu_power: "/amdcpu/0/power/0", gpu_temp: "/gpu-nvidia/0/temperature/0",
        gpu_load: "/gpu-nvidia/0/load/0", gpu_power: "/gpu-nvidia/0/power/0", ram_load: "/ram/load/0" } } };
  }
  async series(ids) { const now = Date.now() / 1000, o = {}; for (const i of ids) if (i) o[i] = (this.hist[i] || []).map(([t, v]) => [t - now, v]); return o; }
  async inventory() {
    await new Promise(r => setTimeout(r, 500));
    return { sections: {
      Processor: [{ Model: "AMD Ryzen 7 7800X3D 8-Core Processor", "Cores / Threads": "8 / 16", "Max clock": "4201 MHz", "L2 / L3 cache": "8 MB / 96 MB", Socket: "AM5", Virtualization: "Enabled" }],
      Graphics: [{ Model: "NVIDIA GeForce RTX 4070 SUPER", Driver: "32.0.15.6614 (2026-10-21)", Display: "2560x1440 @ 165 Hz" }],
      Motherboard: [{ Manufacturer: "ASUSTeK COMPUTER INC.", Model: "TUF GAMING B650-PLUS WIFI", Revision: "Rev 1.xx" }, { BIOS: "American Megatrends 3222", "BIOS date": "2026-03-14" }],
      Memory: [{ Total: "32.0 GB", Sticks: "2", Type: "DDR5", "Rated speed": "6000 MT/s", "Running speed": "6000 MT/s" },
        { Slot: "DIMM_A2", Size: "16.0 GB", "Maker / Part": "G.Skill F5-6000J3038F16G", Speed: "6000 / 6000 MT/s" },
        { Slot: "DIMM_B2", Size: "16.0 GB", "Maker / Part": "G.Skill F5-6000J3038F16G", Speed: "6000 / 6000 MT/s" }],
      Storage: [{ Drive: "Samsung SSD 990 PRO 2TB", Type: "SSD (NVMe)", Size: "1.8 TB", Health: "Healthy", Firmware: "4B2QJXD7" },
        { Volume: "C:\\", "File system": "NTFS", Used: "1.1 TB of 1.8 TB (61%)" }],
      Displays: [{ Monitor: "LG ULTRAGEAR", "Maker code": "GSM" }],
      Network: [{ Adapter: "Realtek Gaming 2.5GbE Family Controller", MAC: "A1:B2:C3:D4:E5:F6", Link: "1000 Mbps" }],
      Audio: [{ Device: "Realtek USB Audio", Status: "OK" }, { Device: "NVIDIA High Definition Audio", Status: "OK" }],
      System: [{ OS: "Microsoft Windows 11 Home", Build: "10.0.26100 (64-bit)", Uptime: "0d 3h 12m" }] },
      drives: [{ Name: "Samsung SSD 990 PRO 2TB", Verdict: "Good", Temp: 41, Wear: 2, PowerOnHours: 1840, ReadErrors: 0, WriteErrors: 0, Notes: "No problems found" }] };
  }
  async export_report() { return "C:\\Users\\you\\AppData\\Roaming\\RigLab\\reports\\RigLab_report.html"; }
  async diagnostics() {
    return [
      { id: "admin", title: "Running as administrator", ok: true, detail: "Good." },
      { id: "lhm", title: "Detailed sensor library (LibreHardwareMonitor)", ok: true, detail: "Loaded (v0.9.6 LibreHardwareMonitor.zip (netfx 4)) via netfx.", fix: "redownload_lhm", fix_label: "Re-download" },
      { id: "pawnio", title: "PawnIO driver", ok: true, detail: "Installed." },
      { id: "cpu_temp", title: "CPU temperature & power", ok: true, detail: "Reading." },
      { id: "gpu", title: "Graphics card sensors", ok: true, detail: "Reading." },
      { id: "fans_mobo", title: "Motherboard fan headers", ok: true, detail: "2 controllable." },
      { id: "fans_hub", title: "USB fan hubs / AIOs (Corsair Commander Core/XT/ST/Pro, NZXT…)", ok: true, detail: "3 channels controllable via liquidctl.", fix: "rescan_hubs", fix_label: "Rescan" },
      { id: "openrgb", title: "OpenRGB (lighting)", ok: true, detail: "Connected." }];
  }
  async fix(a) { if (a === "redownload_lhm") { this.lhm_install(false); return "started"; } await new Promise(r => setTimeout(r, 800)); return "Done (preview mode)"; }
  async lhm_install() {
    const t0 = Date.now(), lines = ["Downloading latest release…"];
    this.lhm = { t0, lines };
    return true;
  }
  async lhm_status() {
    const L = this.lhm; if (!L) return { running: false, progress: 0, log: [], lhm: "active", ok: null };
    const el = (Date.now() - L.t0) / 1000, p = Math.min(1, el / 4);
    if (el > 1.5 && L.lines.length === 1) L.lines.push("  got 6.3 MB", "  build type: netfx 4.7.2", "Unpacked 55 files (netfx 4.7.2)");
    if (el > 3 && L.lines.length === 4) L.lines.push("Installed latest release (netfx 4.7.2).", "Starting sensors…");
    const running = el < 4;
    return { running, progress: p, step: running ? `Downloading latest release… ${(p * 6.3).toFixed(1)} / 6.3 MB` : "", log: L.lines, ok: running ? null : true, error: null, lhm: el < 5 ? "starting" : "active", installed: "latest release (netfx 4.7.2)" };
  }
  async drives() { return ["C:\\", "D:\\"]; }
  async bench_start(o) {
    Object.assign(this.bench, { running: true, progress: 0, results: [], error: null });
    const steps = [o.cpu && "CPU single-core", o.cpu && "CPU multi-core", o.memory && "Memory", o.disk && "Disk"].filter(Boolean);
    let i = 0;
    const tick = () => {
      this.bench.progress = Math.min(1, this.bench.progress + 0.04);
      this.bench.msg = steps[Math.min(steps.length - 1, Math.floor(this.bench.progress * steps.length))] + "…";
      if (this.bench.progress >= 1) {
        this.bench.running = false; this.bench.msg = "Done";
        const R = [];
        if (o.cpu) R.push({ name: "CPU single-core", score: 9480, unit: "pts", details: { "Integer ops/s": 1288, "FP GFLOPS": 69.8 } },
          { name: "CPU multi-core", score: 71230, unit: "pts", details: { "Integer ops/s": 9930, "FP GFLOPS": 512.3, Threads: 16, Scaling: "7.5x" } });
        if (o.memory) R.push({ name: "Memory bandwidth", score: 38.4, unit: "GB/s", details: { Buffer: "512 MB" } }, { name: "Memory random access", score: 168.2, unit: "M/s", details: {} });
        if (o.disk) R.push({ name: "Disk sequential write", score: 5940, unit: "MB/s", details: {} }, { name: "Disk sequential read", score: 6870, unit: "MB/s", details: {} }, { name: "Disk random 4K read", score: 18300, unit: "IOPS", details: { "Avg latency": "55 µs" } });
        this.bench.results = R;
      } else setTimeout(tick, 120);
      i++;
    };
    tick();
    return true;
  }
  async bench_status() { return this.bench; }
  async bench_finish(gpu) {
    const rows = this.bench.results.map(r => ({ ...r, best: r.score * 0.97, change: 3.1 }));
    if (gpu && gpu.score) rows.push({ name: "GPU 3D render", score: Math.round(gpu.score), unit: "pts", details: { "Avg FPS": gpu.avg_fps.toFixed(1) }, best: null, change: null });
    return rows;
  }
  async bench_history() { return [{ time: "2026-11-10 19:42", results: [{ name: "CPU single-core", score: 9220, unit: "pts" }, { name: "CPU multi-core", score: 69800, unit: "pts" }, { name: "GPU 3D render", score: 15400, unit: "pts" }] }]; }
  async gpu_window() { setTimeout(() => { this.gpuRes = { avg_fps: 214.2, low_fps: 188.4, score: 15620, resolution: "1280x720" }; }, 2500); return true; }
  async gpu_poll() { const r = this.gpuRes; this.gpuRes = null; return r; }
  async gpu_params() { return { mode: "bench", seconds: 20 }; }
  async gpu_result() { return true; }
  async stress_start(o) { this.stress = { running: true, start: Date.now(), o, samples: [], max: 0, errors: 0 }; return true; }
  async stress_stop() { if (this.stress) { this.stress.running = false; this.stress.reason = "stopped by user"; } return true; }
  async stress_status(since) {
    const s = this.stress;
    if (!s) return { running: false, elapsed: 0, errors: 0, iterations: 0, samples: [], total: 0 };
    const el = (Date.now() - s.start) / 1000;
    if (s.running) {
      const tt = 60 + 26 * (1 - Math.exp(-el / 25)) + Math.random() * 1.5;
      s.samples.push([el, +tt.toFixed(1), 48 + Math.random() * 3, 5050 - (tt > 84 ? 120 : 0) + Math.random() * 40, 88 + Math.random() * 6]);
      s.max = Math.max(s.max, tt);
      if (el >= Math.min(s.o.duration, 60)) { s.running = false; s.reason = "completed"; }
    }
    const out = { running: s.running, elapsed: el, errors: 0, iterations: Math.round(el * 410), max_temp: s.max, avg_temp: s.max - 4, peak_clock: 5080,
      end_clock: s.samples.length ? s.samples[s.samples.length - 1][3] : null, max_power: 94, throttling: false, reason: s.reason || "", samples: s.samples.slice(since), total: s.samples.length };
    if (!s.running) out.verdict = s.max >= 90 ? ["PASS (hot)", "No errors, but temps are high."] : ["PASS", "No errors and no throttling detected."];
    return out;
  }
  lightDevs() {
    const L = this.L ||= { set: {}, zones: { "Gigabyte A520I AC|D_LED": { size: 48, unconfirmed: true }, "Corsair Lighting Node Pro|Channel 1": { size: 48, unconfirmed: true }, "Corsair Lighting Node Pro|Channel 2": { size: 48, unconfirmed: true } } };
    const Z = (dev, name, n, min, max) => { const zs = L.zones[dev + "|" + name]; const res = min != null && min !== max; return { name, leds: zs ? (zs.empty ? 0 : zs.size) : n, min: min ?? n, max: max ?? n, resizable: res, per: zs?.per || 0, empty: !!zs?.empty, unconfirmed: !!zs?.unconfirmed }; };
    const D = (name, type, zones, wireless) => { const s = L.set[name] ||= { enabled: true, brightness: 1, order: "RGB", reverse: false, method: "stream" };
      zones.forEach((z, i) => z.index = i); return { key: name, name, type, vendor: "", zones, leds: zones.reduce((a, z) => a + z.leds, 0), modes: ["Direct", "Static"], active_mode: "Direct", settings: s, wireless: !!wireless, native: /Lighting Node/.test(name) }; };
    return [
      D("Gigabyte A520I AC", "Motherboard", [Z("Gigabyte A520I AC", "D_LED", 0, 0, 1024), Z("Gigabyte A520I AC", "LED_C", 1)]),
      D("Gigabyte Radeon RX 7900 GRE GAMING OC", "Gpu", [0, 1, 2, 3, 4].map(i => Z("x", "Zone " + (i + 1), 1))),
      D("Corsair Lighting Node Pro", "Ledstrip", [Z("Corsair Lighting Node Pro", "Channel 1", 0, 0, 204), Z("Corsair Lighting Node Pro", "Channel 2", 0, 0, 204)]),
      D("Logitech G560", "Speaker", ["Left front", "Left rear", "Right front", "Right rear"].map(n => Z("x", n, 1))),
      D("SteelSeries Apex 3", "Keyboard", [Z("x", "Keyboard", 10)]),
      D("Logitech G305 Lightspeed", "Mouse", [Z("x", "Logo", 1)], true)];
  }
  async light_state() {
    if (!this.lightT) this.lightT = Date.now();
    const starting = Date.now() - this.lightT < 2500;
    const devs = starting ? [] : this.lightDevs();
    const leds = devs.filter(d => d.settings.enabled).reduce((a, d) => a + d.leds, 0);
    return { status: this.lightPaused ? "paused" : starting ? "starting" : "running", msg: starting ? "Detecting your RGB devices…" : "", error: null,
      stats: { fps: 30, leds, frames: 0, errors: 0 }, devices: devs, state: this.lightState ||= { effect: "Rainbow sweep", color: "#00c8ff", color2: "#ff00a0", speed: 1, brightness: 1 },
      effects: Object.keys(EFFECT_INFO).filter(e => e !== "Off").concat(["Off"]), palettes: Object.keys(FX_PALETTES), fan_types: { "LL120 / LL140": 16, "QL120 / QL140": 34, "HD120 RGB": 12, "ML120 / ML140 Pro RGB": 4, "SP120 RGB Elite": 8, "Lighting Node LED strip": 10, "LS100 strip (250 mm)": 15 },
      orders: ["RGB", "RBG", "GRB", "GBR", "BRG", "BGR"], exe: "C:\\Program Files\\OpenRGB\\OpenRGB.exe", port: 6743,
      setup: devs.flatMap(d => d.zones.filter(z => z.unconfirmed).map(z => ({ key: d.key, zone: z.name }))) };
  }
  gtCaps() {
    return this.gt ||= { core_offset: { min: -500, max: 500, step: 5, value: 0, default: 0, label: "Core clock offset", unit: "MHz", help: "Shifts the whole boost curve. Raise in +15-30 MHz steps and test each step." },
      core_cap: { min: 1035, max: 3105, step: 15, value: 3105, default: 3105, label: "Max core clock (cap)", unit: "MHz", help: "Undervolt the easy way: cap the clock a little below your stock boost and add a core offset." },
      mem_offset: { min: -1000, max: 3000, step: 10, value: 0, default: 0, label: "Memory clock offset", unit: "MHz", help: "VRAM overclock. Go up +100-200 at a time; if the score drops, back off." },
      power: { min: 100, max: 182, step: 1, value: 170, default: 170, label: "Power limit", unit: "W", help: "Maximum board power." },
      fan_manual: { value: false, label: "Manual fan speed", help: "Off = the card's automatic fan curve." },
      fan_speed: { min: 30, max: 100, step: 1, value: 60, default: null, label: "Fan speed (manual)", unit: "%", help: "Used while Manual fan speed is on." } };
  }
  async gpu_tune_state() { const c = this.gtCaps(); const fac = Object.values(c).every(x => x.default == null || x.value === x.default);
    return { backend: "nvml", backend_label: "Live control via NVIDIA driver (NVML)", error: null, note: null, selected: 0,
      gpus: [{ name: "NVIDIA GeForce RTX 3060", vendor: "nvidia", integrated: false }],
      gpu: { name: "NVIDIA GeForce RTX 3060", vram_mb: 12288, driver: "576.88", bios: "94.06.2F.00.9A" }, caps: c, at_factory: fac, pending: this.gtPend || {} }; }
  async gpu_setup_check() { await new Promise(r => setTimeout(r, 900));
    return { ready: true, gpu: { name: "NVIDIA GeForce RTX 3060", vendor: "nvidia" }, steps: [
      { id: "detect", title: "Graphics card", state: "ok", text: "NVIDIA GeForce RTX 3060 (NVIDIA)" },
      { id: "driver", title: "Driver", state: "warn", text: "Installed 576.88. NVIDIA's newest for your card is 581.57. Newer drivers fix tuning bugs and add support.", action: "install_nvidia", label: "Download & install 581.57" },
      { id: "admin", title: "Administrator rights", state: "ok", text: "RigLab runs as administrator." },
      { id: "interface", title: "Tuning interface", state: "ok", text: "Live control via NVIDIA driver (NVML) - 6 controls found." },
      { id: "controls", title: "Controls", state: "ok", text: "Every slider was tested and the driver accepts changes: Core clock offset, Memory clock offset, Power limit." },
      { id: "fps", title: "FPS capture (PresentMon)", state: "ok", text: "Ready for third-party benchmarks and games." }] }; }
  async gpu_setup_fix() { this.fixT = Date.now(); return { ok: true }; }
  async gpu_setup_job() { const p = Math.min(100, Math.round((Date.now() - this.fixT) / 40)); return p < 100 ? { running: true, msg: `Downloading… ${Math.round(p * 6.5)} / 650 MB`, pct: p } : { running: false, ok: true, msg: "NVIDIA installer 581.57 started. Choose Express installation." }; }
  async gpu_select() { return this.gpu_tune_state(); }
  async gpu_tune_apply(v) { for (const [k, x] of Object.entries(v)) this.gtCaps()[k].value = x; this.gtPend = { state: "unverified" }; return { result: Object.fromEntries(Object.keys(v).map(k => [k, "ok"])), state: await this.gpu_tune_state() }; }
  async gpu_tune_reset() { for (const c of Object.values(this.gtCaps())) if (c.default != null) c.value = c.default; this.gtCaps().fan_manual.value = false; this.gtPend = {}; return { ok: true, state: await this.gpu_tune_state() }; }
  async gpu_tune_confirm() { this.gtPend = { state: "verified" }; return true; }
  async gpu_metrics() { const c = this.gtCaps(), t = Date.now() / 1000, load = this.gtRun?.running ? 99 : 4;
    const clk = Math.min(c.core_cap.value, 2640 + c.core_offset.value);
    return { clock: load > 50 ? Math.round(clk + Math.sin(t) * 15) : 210, vram_clock: load > 50 ? 10501 + c.mem_offset.value : 405, board_power: load > 50 ? Math.round(Math.min(c.power.value, 196 * clk / 2640)) : 14,
      temp: load > 50 ? 66 : 36, hotspot: load > 50 ? 78 : 40, voltage: load > 50 ? Math.round(1000 * clk / 2700) : 880, fan_pct: c.fan_manual.value ? c.fan_speed.value : load > 50 ? 52 : 0, usage: load, ...(this.gtRun?.running ? { fps: 142 + Math.round(Math.sin(t) * 6) } : {}) }; }
  async gpu_benchmarks() { return [{ name: "Unigine Heaven", exe: "C:\\Program Files (x86)\\Unigine\\Heaven Benchmark 4.0\\heaven.bat" }, { name: "3DMark", exe: "C:\\...\\3DMark.exe" }]; }
  async gpu_bench_add() { return this.gpu_benchmarks(); }
  async gpu_run_start(source, exe, seconds, label) { this.gtRun = { running: true, label, source: source === "builtin" ? "builtin" : (exe ? "Heaven" : "external"), t0: Date.now(), seconds: seconds || 0, n: 0 }; return { ok: true }; }
  async gpu_run_status() { const r = this.gtRun; if (!r) return { running: false };
    const el = Math.round((Date.now() - r.t0) / 1000); const m = await this.gpu_metrics(); r.n++;
    if (r.running && (r.stopNow || (r.seconds && el >= Math.min(r.seconds, 6)))) { r.running = false; const c = this.gtCaps(); const k = (Math.min(c.core_cap.value, 2640 + c.core_offset.value) / 2640) * (1 + c.mem_offset.value / 30000);
      const run = { id: Date.now(), label: r.label, source: r.source, time: new Date().toLocaleString(), settings: Object.fromEntries(Object.entries(c).map(([a, b]) => [a, b.value])), at_factory: false,
        stats: { score: r.score || Math.round(14800 * k), fps_avg: +(142 * k).toFixed(1), fps_low: +(118 * k).toFixed(1), clock_avg: m.clock, clock_max: m.clock + 30, vram_clock_avg: m.vram_clock,
          power_avg: m.board_power, power_max: m.board_power + 22, voltage_avg: m.voltage, temp_avg: 63, fps_low01: +(96 * k).toFixed(1), temp_max: 66, hotspot_max: 84, fan_avg: 1460, usage_avg: 98.6, fps_per_watt: +((142 * k) / m.board_power).toFixed(3) },
        trace: [...Array(60)].map((_, i) => [i, Math.round(m.clock - 20 + Math.sin(i / 4) * 25), m.board_power, 60, 140]) };
      (this.gtRuns ||= []).push(run); r.saved = run.id; }
    return { label: r.label, source: r.source, running: r.running, msg: r.source === "builtin" ? "Running RigLab's 3D benchmark…" : "Recording while the benchmark runs - stop here when it finishes.", live: m, elapsed: el, seconds: r.seconds, n: r.n, saved: r.saved }; }
  async gpu_run_stop(score) { if (this.gtRun) { this.gtRun.stopNow = true; this.gtRun.score = score ? +score : null; } return true; }
  demoRun(id, label, k, ago) {
    const tr = [...Array(120)].map((_, i) => { const t = i / 2, warm = Math.min(1, t / 20);
      return [t, Math.round(1890 * k - (i % 9) * 12 - (k > 1 && i > 70 ? 45 : 0)), Math.round(150 + 20 * k * warm), Math.round(58 + 18 * warm * k), +(118 * k + Math.sin(i / 3) * 5).toFixed(1), Math.round(72 + 22 * warm * k), 98, 7501 + (k > 1 ? 600 : 0), Math.round(40 + 20 * warm), k > 1 && i > 70 ? 0x24 : 0x4]; });
    const col = (j) => tr.map(p => p[j]); const avg = (a) => +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(1);
    const fps = avg(col(4)), pw = avg(col(2));
    return { id, label, source: "Unigine Heaven", gpu: "NVIDIA GeForce RTX 3060", time: new Date(Date.now() - ago).toISOString().slice(0, 16).replace("T", " "), duration: 60,
      settings: k > 1 ? { core_offset: 120, mem_offset: 800, power: 182, core_cap: 3105 } : { core_offset: 0, mem_offset: 0, power: 170, core_cap: 3105 },
      stats: { fps_avg: fps, fps_max: Math.max(...col(4)), fps_low: +(fps * (k > 1 ? 0.71 : 0.78)).toFixed(1), fps_low01: +(fps * 0.55).toFixed(1), score: Math.round(fps * 40), fps_per_watt: +(fps / pw).toFixed(3),
        clock_avg: avg(col(1)), clock_max: Math.max(...col(1)), clock_p5: Math.min(...col(1)), clock_drop_pct: k > 1 ? 9.4 : 4.1, vram_clock_avg: avg(col(7)), power_avg: pw, power_max: Math.max(...col(2)), power_limit: k > 1 ? 182 : 170,
        temp_avg: avg(col(3)), temp_max: Math.max(...col(3)), hotspot_max: Math.max(...col(5)), hotspot_delta_max: 16, usage_avg: 98, pct_power_limited: k > 1 ? 62 : 85, pct_thermal_limited: k > 1 ? 18 : 0,
        fan_pct_max: 68, vram_used_max: 6900, vram_total: 12288, spikes: k > 1 ? 9 : 4, driver_resets: 0, app: "Heaven.exe" }, trace: tr };
  }
  async overlay_config() { const o = this.cfg?.overlay || {}; return { mode: o.mode || "full", show_fps: !!o.show_fps, size: o.size || "m", opacity: o.opacity ?? 0.85, fps_color: o.fps_color || "auto", edit: !!this.ovEdit }; }
  async overlay_edit(on) { this.ovEdit = !!on; return { edit: this.ovEdit, x: on ? null : 400, y: on ? null : 60 }; }
  async overlay_corner() { return true; }
  async overlay_fit() { return true; }
  async overlay_fps() {
    const t = Date.now() / 1000, fps = 141 + Math.round(Math.sin(t) * 6);
    return { state: "ok", app: "Cyberpunk2077.exe", fps, low1: 104 + Math.round(Math.sin(t / 3) * 4), frametime: +(1000 / fps).toFixed(2) };
  }
  async gpu_results(runId, baseId) {
    const rs = (this.gtRuns && this.gtRuns.length >= 1) ? this.gtRuns : (this.gtRuns = [this.demoRun(1, "Before", 1, 864e5), this.demoRun(2, "After", 1.07, 36e5)]);
    const run = rs.find(r => r.id === runId) || rs[rs.length - 1], base = baseId === -1 ? null : rs.find(r => r.id === baseId) || rs.find(r => r.label === "Before" && r.id !== run.id) || null;
    const issues = base && run.stats.pct_thermal_limited ? [
      { level: "warn", title: `Thermal throttling ${run.stats.pct_thermal_limited}% of the time`, detail: "The driver reported it was slowing the card down because of heat.", fix: "Cooling first: fan curve, airflow, then undervolt." },
      { level: "good", title: `${((run.stats.fps_avg - base.stats.fps_avg) / base.stats.fps_avg * 100).toFixed(1)}% average FPS vs Before`, detail: "The tune is working." },
      { level: "good", title: "Smooth frame pacing", detail: "1% lows are 71% of the average." },
      { level: "info", title: `Power-limited ${run.stats.pct_power_limited}% of the time`, detail: "Normal under full load: the card is using its whole power budget.", fix: "Raise the power limit if your card allows it, or undervolt." }]
      : [{ level: "good", title: `Temperatures are fine (peak ${run.stats.temp_max} °C)`, detail: "Comfortably below the throttle point." }, { level: "good", title: "Smooth frame pacing", detail: "1% lows are 78% of the average." }];
    const lvl = issues.some(i => i.level === "bad") ? "bad" : issues.some(i => i.level === "warn") ? "warn" : "good";
    return { runs: rs.map(r => ({ id: r.id, label: r.label, source: r.source, time: r.time })), run, base, issues,
      verdict: { level: lvl, title: lvl === "warn" ? "Worth a look" : "Healthy", text: lvl === "warn" ? "It works, but some things are holding the card back." : "No problems found." } };
  }
  async gpu_runs() { return this.gtRuns ||= []; }
  async gpu_run_edit(id, label, score, del) { const r = this.gtRuns || []; const x = r.find(q => q.id === id); if (x && del) r.splice(r.indexOf(x), 1); else if (x && score) x.stats.score = +score; return r; }
  async ui_set(v) { Object.assign(this.uiCfg ||= {}, v); return this.uiCfg; }
  async light_reset() { return true; }
  async light_connect() { this.lightPaused = false; this.lightT = Date.now(); return true; }
  async light_pause(on) { this.lightPaused = on; return on; }
  async light_pick_exe() { return this.light_state(); }
  async light_set(s) { Object.assign(this.lightState, s); return true; }
  async light_device(k, s) { Object.assign(this.L.set[k], s); return this.light_state(); }
  async light_zone(k, z, size, per, empty) { this.L.zones[k + "|" + z] = { size, per: per || 0, empty: !!empty }; return this.light_state(); }
  async light_test() { return true; }
  async light_identify() { return true; }
  async light_rescan() { return this.light_state(); }
  async light_fix_openrgb() { return "Restored your original OpenRGB settings."; }
  async light_report() { return "RigLab lighting report (preview mode)"; }
  async light_map() {
    const devs = this.lightDevs().filter(d => d.settings.enabled), fx = [];
    devs.forEach(d => d.zones.forEach(z => {
      if (!z.leds) return; const key = d.key + "|" + z.name;
      if (z.per && z.leds >= z.per) for (let i = 0; i < Math.floor(z.leds / z.per); i++) fx.push({ id: `${key}#${i}`, device: d.key, zone: z.name, start: i * z.per, count: z.per, kind: "fan", label: `${z.name} · fan ${i + 1}` });
      else fx.push({ id: key + "#0", device: d.key, zone: z.name, start: 0, count: z.leds, kind: "strip", label: z.name });
    }));
    fx.forEach((f, i) => { f.x = i % 5; f.y = Math.floor(i / 5); });
    for (const f of fx) { const sv = (this.mapSaved || []).find(q => q.id === f.id); if (sv && sv.count === f.count) Object.assign(f, { x: sv.x, y: sv.y, kind: sv.kind, label: sv.label }); }
    return { fixtures: fx, paint: this.paint || {}, effects: [] };
  }
  async light_map_save(f) { this.mapSaved = f; return true; }
  async light_paint_save(p) { this.paint = p; return true; }
  async rgb_off() { this.lightState.effect = "Off"; return "ok"; }
  async fans_state() {
    const snap = this.defs;
    const ctrls = snap.filter(d => d.ctrl).map(d => {
      const n = (d.name.match(/\d+/) || [""])[0];
      const rpm = snap.find(o => o.kind === "Fan" && o.hw === d.hw && ((o.name.match(/\d+/) || [""])[0] === n));
      return { id: d.id, name: d.name, hw: d.hw, value: Math.round(d.value), rpm: rpm ? Math.round(rpm.value) : null, hub: d.id.startsWith("/liquidctl"), pump: false,
        curve: this.curves[d.id] || null, applied: null };
    });
    const temps = snap.filter(d => d.kind === "Temperature").map(d => ({ id: d.id, name: `${d.hw} › ${d.name}`, value: +d.value.toFixed(1) }));
    return { controls: ctrls, temps, enabled: this.fanOn, presets: {
      Silent: [[30, 20], [50, 30], [65, 50], [75, 75], [85, 100]], Balanced: [[30, 25], [45, 35], [60, 55], [72, 80], [82, 100]],
      Performance: [[30, 40], [45, 55], [60, 75], [70, 90], [78, 100]], "Full speed": [[0, 100], [100, 100]] } };
  }
  async fans_set_curve(id, source, points, pump) { this.curves[id] = { source, points, pump, applied: 55 }; return true; }
  async fans_remove(id) { delete this.curves[id]; return true; }
  async fans_enable(on) { this.fanOn = on; return on; }
  async fans_manual() { return true; }
  async tweaks_state() {
    return { admin: true, tweaks: [
      { id: "game_mode", name: "Windows Game Mode", desc: "Prioritises the game you're playing and pauses Windows Update restarts while gaming. Recommended ON.", on: true, admin: false, reboot: false, cat: "Gaming" },
      { id: "hags", name: "Hardware-accelerated GPU scheduling", desc: "Lets the GPU manage its own memory scheduling. Needed for DLSS Frame Generation. Recommended ON.", on: true, admin: true, reboot: true, cat: "Gaming" },
      { id: "game_dvr", name: "Xbox Game Bar background recording", desc: "Constantly records gameplay so you can save clips. Costs a few FPS.", on: false, admin: false, reboot: false, cat: "Gaming" },
      { id: "mouse_accel", name: "Mouse acceleration", desc: "Cursor moves further when you move the mouse fast. Most FPS players turn this OFF.", on: false, admin: false, reboot: false, cat: "Input" },
      { id: "transparency", name: "Transparency effects", desc: "Windows blur/glass effects.", on: true, admin: false, reboot: false, cat: "Visual" },
      { id: "net_throttle", name: "Multimedia network throttling", desc: "Windows limits network traffic while media plays. OFF can help online games.", on: true, admin: true, reboot: true, cat: "Network" }],
      plans: [{ guid: "a", name: "Balanced", active: true }, { guid: "b", name: "High performance", active: false }, { guid: "c", name: "Power saver", active: false }],
      gpu: { name: "NVIDIA GeForce RTX 4070 SUPER", min: 100, max: 242, cur: 220 },
      startup: [{ i: 0, name: "Discord", cmd: "C:\\Users\\you\\AppData\\Local\\Discord\\Update.exe --processStart Discord.exe", where: "Current user", on: true },
        { i: 1, name: "Steam", cmd: "\"C:\\Program Files (x86)\\Steam\\steam.exe\" -silent", where: "Current user", on: true },
        { i: 2, name: "OpenRGB", cmd: "C:\\Program Files\\OpenRGB\\OpenRGB.exe --startminimized --server", where: "Current user", on: true },
        { i: 3, name: "EpicGamesLauncher", cmd: "\"C:\\Program Files (x86)\\Epic Games\\Launcher\\EpicGamesLauncher.exe\" -silent", where: "Current user", on: false }] };
  }
  async tweak_set() { return "ok"; }
  async restore_point() { await new Promise(r => setTimeout(r, 900)); return { ok: true, msg: "Restore point created" }; }
  async set_power_plan() { return true; }
  async add_ultimate() { return true; }
  async set_gpu_power() { return "ok"; }
  async startup_set() { return "ok"; }
  async junk(clean) { await new Promise(r => setTimeout(r, 600)); return { bytes: 2.3e9, files: 4821 }; }
  async settings() { return this.cfg; }
  async save_settings(c) { this.cfg = c; return true; }
  async log_toggle() { this.logging = !this.logging; return { active: this.logging, path: "sensors_20261114.csv" }; }
  async open_folder() { return true; }
  async startup_notes() { return [{ kind: "info", text: "Detected: RAM speed changed: 4800 MT/s → 6000 MT/s" }]; }
  async oc_state() {
    const inv = await this.inventory();
    const profile = { cpu: { name: "AMD Ryzen 7 7800X3D 8-Core Processor", vendor: "amd", series: 7000, x3d: true, platform: "AM5", zen: 4, boost_override: false, pbo: true },
      gpu: { name: "NVIDIA GeForce RTX 3060", vendor: "nvidia" }, ram: { type: "DDR5", rated: 6000, running: 6000, total: "32.0 GB", profile_on: true },
      board: { name: "ASUSTeK COMPUTER INC. TUF GAMING B650-PLUS WIFI", vendor: "asus", bios: "American Megatrends 3222", bios_date: "2026-03-14" } };
    const pbo = "Ai Tweaker → Precision Boost Overdrive";
    const co = v => ({ id: "cpu_co" + Math.abs(v), title: `Curve Optimizer: all cores ${v}`, where: pbo + " → Curve Optimizer", set: `Curve Optimizer = All Cores, Sign = Negative, Magnitude = ${Math.abs(v)}`, risk: "medium",
      why: "An undervolt: same clocks with less voltage, so lower temps and higher sustained boost. Every chip is different - the per-core test finds the limit of each core.", test: { kind: "core_cycle", minutes: 0 }, rollback: `If a core fails, go to Per Core mode and give only that core ${v + 5} (or less negative).` });
    const plans = {
      cpu: { title: "Processor", steps: [{ id: "cpu_baseline", title: "Record a baseline", where: "RigLab", set: "Run the Benchmark page (CPU) and a 10-minute CPU stress test with nothing changed.", why: "So every later step can be measured against stock.", risk: "none", test: { kind: "cpu", minutes: 10 } },
        { id: "cpu_pbo", title: "Turn on Precision Boost Overdrive", where: pbo, set: "Precision Boost Overdrive = Advanced (limits stay locked on X3D chips)", why: "Lets the CPU boost harder for longer when cooling allows. Fully automatic and safe.", risk: "low", test: { kind: "cpu", minutes: 15 }, rollback: "Set Precision Boost Overdrive back to Auto." },
        co(-10), co(-20), co(-25), co(-30),
        { id: "cpu_temp", title: "Temperature limit (optional, for quieter/cooler)", where: pbo, set: "Platform Thermal Throttle Limit = Manual, 85 °C", why: "Trades a few % of all-core performance for a lot less heat and fan noise.", risk: "none", test: { kind: "cpu", minutes: 10 } }],
        limits: ["Never set a fixed high Vcore for daily use - Curve Optimizer is the safe way on Ryzen.", "Ryzen 7000/9000 SoC voltage must stay at or below 1.30 V.", "X3D chips: no manual multiplier overclocking - PBO/Curve Optimizer only."] },
      ram: { title: "Memory", steps: [{ id: "ram_expo", title: "Turn on EXPO/XMP (6000 MT/s)", where: "Ai Tweaker → Ai Overclock Tuner → EXPO I (or EXPO II)", set: "Select EXPO (AMD) / XMP Profile 1. Save & exit.", why: "Already on - nothing to do.", risk: "low", done: true, test: { kind: "ram", minutes: 30 } },
        { id: "ram_fclk", title: "Infinity Fabric 2000 MHz", where: "Ai Tweaker → FCLK Frequency", set: "FCLK Frequency = 2000 MHz; UCLK DIV1 MODE = UCLK=MEMCLK", why: "Speeds up the link between the CPU chiplets and memory.", risk: "medium", test: { kind: "ram", minutes: 30 }, rollback: "Set FCLK back to Auto." }],
        limits: ["DDR5 VDD/VDDQ: stay at or below 1.40 V for daily use."] },
      gpu: { title: "Graphics", limits: ["After a driver crash (black screen) the last change was unstable - back it off.", "Keep the GPU below about 83 °C."], steps: [
        { id: "gpu_baseline", bench: true, title: "Record a baseline", where: "GPU tuning tab → Performance: before & after", set: "Run a benchmark at stock and save it as Before.", why: "Every later change is measured against it.", risk: "none", test: { kind: "gpu", minutes: 5 } },
        { id: "gpu_nv_power", controls: ["power"], title: "Max out the power limit", where: "Right here - sliders below", set: "Slide the power limit to its maximum.", why: "Lets the card hold higher boost clocks.", risk: "low", test: { kind: "gpu", minutes: 10 } },
        { id: "gpu_nv_core", controls: ["core_offset"], title: "Core clock offset", where: "Right here - sliders below", set: "+30 MHz at a time; run a benchmark after each step.", why: "Shifts the whole boost curve up.", risk: "medium", test: { kind: "gpu", minutes: 15 }, rollback: "Lower by 30 MHz, or Reset to stock." },
        { id: "gpu_nv_mem", controls: ["mem_offset"], title: "Memory clock offset", where: "Right here - sliders below", set: "+200 MHz at a time. Stop when the score stops rising.", why: "More memory bandwidth.", risk: "medium", test: { kind: "gpu", minutes: 15 } },
        { id: "gpu_nv_uv", controls: ["core_cap", "core_offset"], title: "Optional: undervolt", where: "Right here - sliders below", set: "Cap the clock at your average benchmark clock and add +100-150 MHz core offset.", why: "Same performance at lower voltage.", risk: "medium", test: { kind: "gpu", minutes: 15 } }] },
      board: { title: "Motherboard", steps: [{ id: "mb_bios", title: "Update the BIOS first", where: "Board support page", set: "Current: American Megatrends 3222 (2026-03-14).", why: "New BIOSes fix memory compatibility and add features.", risk: "low", test: null }], limits: [] } };
    return { profile, plans, progress: { cpu_baseline: { state: "passed" }, cpu_pbo: { state: "passed" }, cpu_co10: { state: "passed" }, cpu_co20: { state: "applied" } },
      journal: [{ time: Date.now() / 1000 - 600, kind: "applied", text: "Applied: Curve Optimizer: all cores -20" }, { time: Date.now() / 1000 - 4000, kind: "passed", text: "Curve Optimizer: all cores -10: PASSED - No errors" },
        { time: Date.now() / 1000 - 90000, kind: "detected", text: "RAM speed changed: 4800 MT/s → 6000 MT/s" }],
      windows: { available: true, boost_mode: 2, max_state: 100, modes: { 0: "Disabled (no boost - coolest)", 1: "Enabled", 2: "Aggressive (default)", 3: "Efficient Enabled", 4: "Efficient Aggressive" } }, validation: this.ocv || null };
  }
  async oc_step() { return {}; }
  async oc_note() { return {}; }
  async oc_windows_set() { return { ok: true }; }
  async oc_validate(step, kind, minutes, title) { this.ocv = { step, kind, title, start: Date.now() / 1000, duration: 30, state: "running" }; return true; }
  async oc_validation() {
    const v = this.ocv; if (!v) return null;
    const el = Date.now() / 1000 - v.start;
    if (el > v.duration && v.state === "running") Object.assign(v, { state: "passed", verdict: ["PASS", "No errors and no throttling detected."], per_core: Object.fromEntries([...Array(8)].map((_, i) => [i, { errors: 0 }])) });
    return { ...v, elapsed: Math.min(el, v.duration), core: Math.floor(el / 4) % 8, errors: 0, max_temp: 71 };
  }
  async oc_validation_stop() { if (this.ocv) this.ocv.duration = 0; return true; }
  async crashes_scan(days) {
    await new Promise(r => setTimeout(r, 600));
    const now = Date.now() / 1000;
    const stability = [...Array(days)].map((_, i) => ({ time: now - (days - i) * 86400, v: Math.min(10, 6 + i * 0.12 - (i === days - 3 ? 2.5 : 0)) }));
    return { days, debugger: false, dumps: [], stability, incidents: [
      { time: now - 3 * 3600, type: "bsod", severity: 3, title: "Blue screen - WHEA_UNCORRECTABLE_ERROR", summary: "The CPU reported a hardware error it couldn't correct.",
        cause: "Unstable CPU overclock/undervolt, RAM/Infinity Fabric (FCLK) instability, SoC voltage, overheating. WHEA errors point at APIC ID 6 - on Ryzen with SMT that's physical core ≈ 3. If you use Curve Optimizer, raise (less negative) that core's value. Your last tuning change ('Applied: Curve Optimizer: all cores -20') was 14 min before this - try undoing it.",
        bugcheck: { code: "0x124", name: "WHEA_UNCORRECTABLE_ERROR" }, dumps: ["C:\\Windows\\Minidump\\111426-7031-01.dmp"], recent_change: { text: "Applied: Curve Optimizer: all cores -20", ago_min: 14 },
        events: [{ time: now - 3 * 3600, title: "Hardware error (WHEA) - fatal", detail: "Processor Core · Machine Check Exception · APIC ID 6", src: "Microsoft-Windows-WHEA-Logger", id: 18 },
          { time: now - 3 * 3600 + 40, title: "Unexpected shutdown / restart", detail: "Bug check 0x124 recorded with it.", src: "Microsoft-Windows-Kernel-Power", id: 41 },
          { time: now - 3 * 3600 + 90, title: "Blue screen: WHEA_UNCORRECTABLE_ERROR (0x124)", detail: "The CPU reported a hardware error it couldn't correct.", src: "Microsoft-Windows-WER-SystemErrorReporting", id: 1001 }] },
      { time: now - 2 * 86400, type: "gpu", severity: 2, title: "Graphics driver crash / reset", summary: "The graphics card stopped responding; Windows reset the driver.",
        cause: "Usually an unstable GPU tuning (undervolt or VRAM overclock in Adrenalin), GPU temperatures, or a driver bug. Back off the last Adrenalin change first.", dumps: [],
        events: [{ time: now - 2 * 86400, title: "Graphics driver stopped responding and recovered", detail: "Display driver amdkmdag stopped responding and has successfully recovered.", src: "Display", id: 4101 }] },
      { time: now - 6 * 86400, type: "app", severity: 1, title: "App crash: FortniteClient-Win64-Shipping.exe", summary: "Faulting module: d3d12core.dll",
        cause: "A single app crashing is usually that app's bug. If many different apps crash at random, suspect unstable RAM/CPU tuning.", dumps: [],
        events: [{ time: now - 6 * 86400, title: "FortniteClient-Win64-Shipping.exe crashed", detail: "Faulting module: d3d12core.dll", src: "Application Error", id: 1000 }] }] };
  }
  async crash_analyze() { this.an = Date.now(); return { state: "running" }; }
  async crash_analyze_status() {
    const el = (Date.now() - this.an) / 1000;
    if (el < 3) return { state: "running", elapsed: el };
    return { state: "done", elapsed: el, raw: "...\n!analyze -v output...", result: { PROBABLY_CAUSED_BY: "AuthenticAMD.sys", IMAGE_NAME: "AuthenticAMD.sys", PROCESS_NAME: "System",
      FAILURE_BUCKET_ID: "0x124_0_AuthenticAMD_PROCESSOR_CACHE_IMAGE_AuthenticAMD.sys" } };
  }
  async install_windbg() { return "WinDbg installer opened in a new window."; }
  async open_url(u) { window.open(u, "_blank"); return true; }
}
