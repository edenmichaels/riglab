"""GPU results readout: turn a recorded performance run into numbers, graphs and a list of things to worry about.

analyze(run, baseline) checks the run against simple, explainable rules. Every issue has a level
(bad / warn / info / good), what was measured, why it matters and what to do about it.
"""
from __future__ import annotations

from . import gputune

LEVEL_ORDER = {"bad": 0, "warn": 1, "info": 2, "good": 3}


def _issue(level, title, detail, fix=None, metric=None):
    return {"level": level, "title": title, "detail": detail, "fix": fix, "metric": metric}


def analyze(run: dict, base: dict | None = None) -> dict:
    s = run.get("stats", {})
    out = []
    vendor = "nvidia" if any(k in (run.get("settings") or {}) for k in ("core_offset", "mem_offset")) else \
        "amd" if any(k in (run.get("settings") or {}) for k in ("core_max", "voltage")) else "other"
    t_lim = 83 if vendor == "nvidia" else 90           # where the card starts slowing itself down

    # ---------------------------------------------------------------- stability
    resets = s.get("driver_resets") or 0
    if resets:
        out.append(_issue("bad", "The graphics driver crashed during the run",
                          f"Windows logged {resets} display-driver reset(s) while this run was recording. That's the classic sign of an "
                          "overclock or undervolt that's too aggressive.",
                          "Undo the last change (or press Reset to stock on the GPU tuning tab) and test again.", "driver_resets"))

    # ---------------------------------------------------------------- temperatures
    tmax, hs = s.get("temp_max"), s.get("hotspot_max")
    if tmax is not None:
        if tmax >= t_lim + 5:
            out.append(_issue("bad", f"GPU ran very hot ({tmax:.0f} °C)", f"The card throttles from about {t_lim} °C, so it was losing clock speed.",
                              "Improve case airflow, raise the fan curve, or lower the power limit/undervolt.", "temp_max"))
        elif tmax >= t_lim:
            out.append(_issue("warn", f"GPU reached its throttle temperature ({tmax:.0f} °C)", f"Above about {t_lim} °C the card starts to drop its clocks.",
                              "A more aggressive fan curve or a small undervolt keeps it cooler.", "temp_max"))
        else:
            out.append(_issue("good", f"Temperatures are fine (peak {tmax:.0f} °C)", "Comfortably below the throttle point.", None, "temp_max"))
    if hs is not None and hs >= (100 if vendor != "nvidia" else 95):
        out.append(_issue("warn", f"Hotspot is high ({hs:.0f} °C)", "The hottest point on the chip is close to its limit.", "Lower the voltage or improve cooling.", "hotspot_max"))
    hd = s.get("hotspot_delta_max")
    if hd is not None and hd >= 25:
        out.append(_issue("warn", f"Large gap between core and hotspot temperature ({hd:.0f} °C)",
                          "A gap over about 20-25 °C usually means the thermal paste has dried out or the cooler isn't seated evenly.",
                          "Worth a repaste if temperatures keep climbing.", "hotspot_delta_max"))

    # ---------------------------------------------------------------- limits / throttling
    pp, pt, ph = s.get("pct_power_limited"), s.get("pct_thermal_limited"), s.get("pct_hw_slowdown")
    if pt:
        out.append(_issue("bad" if pt >= 20 else "warn", f"Thermal throttling {pt}% of the time", "The driver reported it was slowing the card down because of heat.",
                          "Cooling first: fan curve, airflow, then undervolt.", "pct_thermal_limited"))
    if ph:
        out.append(_issue("bad" if ph >= 10 else "warn", f"Hardware slowdown {ph}% of the time",
                          "The card pulled its clocks down hard (overheating VRAM/power stage or the PSU can't keep up).",
                          "Check the power cables are fully seated, and that the PSU is big enough.", "pct_hw_slowdown"))
    if pp is not None:
        if pp >= 60:
            out.append(_issue("info", f"Power-limited {pp}% of the time",
                              "Normal under full load: the card is using its whole power budget, so that's what caps the clocks now.",
                              "Raise the power limit if your card allows it, or undervolt to get more clock out of the same power.", "pct_power_limited"))
    elif s.get("power_limit") and s.get("power_max") and s["power_max"] >= s["power_limit"] * 0.97:
        out.append(_issue("info", "The card hit its power limit", f"Peak {s['power_max']:.0f} W of {s['power_limit']} W allowed.",
                          "Raise the power limit, or undervolt.", "power_max"))
    drop = s.get("clock_drop_pct")
    if drop is not None and drop >= 12 and not pt:
        out.append(_issue("warn", f"Clocks swing a lot under load (−{drop:.0f}%)", "Clock speed wasn't steady while the card was busy.",
                          "Usually power limit or temperature; see the other notes. Unstable clocks also feel like stutter.", "clock_drop_pct"))

    # ---------------------------------------------------------------- frame pacing
    avg, low, fmax = s.get("fps_avg"), s.get("fps_low"), s.get("fps_max")
    if avg and low:
        ratio = low / avg
        if ratio < 0.5:
            out.append(_issue("bad", "Heavy stutter", f"1% lows are only {ratio * 100:.0f}% of the average ({low:.0f} vs {avg:.0f} FPS).",
                              "Check background apps, shader compilation (run the benchmark twice), RAM/CPU stability and the VRAM overclock.", "fps_low"))
        elif ratio < 0.65:
            out.append(_issue("warn", "Some stutter", f"1% lows are {ratio * 100:.0f}% of the average ({low:.0f} vs {avg:.0f} FPS).",
                              "Often background apps or the CPU; a VRAM overclock that's too high can also cause it.", "fps_low"))
        else:
            out.append(_issue("good", "Smooth frame pacing", f"1% lows are {ratio * 100:.0f}% of the average.", None, "fps_low"))
    if s.get("spikes_per_min") and s["spikes_per_min"] >= 6:
        out.append(_issue("warn", f"{s['spikes']} frame-time spikes ({s['spikes_per_min']}/min)", "Individual frames took far longer than normal - felt as hitches.",
                          "Close overlays/recorders, and check the RAM and CPU are stable.", "spikes"))
    if avg and fmax and fmax - avg < max(2, avg * 0.03) and any(abs(avg - c) < 2.5 for c in (30, 60, 75, 90, 120, 144, 165, 240)):
        out.append(_issue("warn", f"Looks frame-capped at about {round(avg)} FPS",
                          "FPS sits flat on a common refresh rate, so V-Sync or a frame limiter is on. The benchmark isn't showing what the card can really do.",
                          "Turn off V-Sync / frame limits for benchmarking.", "fps_max"))
    use = s.get("usage_avg")
    if use is not None and use < 85 and (avg or s.get("score")):
        out.append(_issue("warn", f"GPU only {use:.0f}% busy on average", "The graphics card was waiting for something else, usually the CPU or a frame cap.",
                          "Higher resolution/settings, or the CPU is the limit in this game.", "usage_avg"))

    # ---------------------------------------------------------------- VRAM / fans
    vu, vt = s.get("vram_used_max"), s.get("vram_total")
    if vu and vt and vu >= vt * 0.95:
        out.append(_issue("warn", f"Video memory full ({vu / 1024:.1f} of {vt / 1024:.0f} GB)", "Running out of VRAM causes big stutters.",
                          "Lower texture quality in this game.", "vram_used_max"))
    fp = s.get("fan_pct_max")
    if fp and fp >= 90:
        out.append(_issue("info", f"Fans near full speed ({fp:.0f}%)", "It works, but it's loud.", "A small undervolt often cuts fan noise a lot.", "fan_pct_max"))

    # ---------------------------------------------------------------- versus the baseline
    if base and base.get("id") != run.get("id"):
        b = base.get("stats", {})
        key = "score" if s.get("score") and b.get("score") else "fps_avg" if s.get("fps_avg") and b.get("fps_avg") else None
        if key:
            gain = (s[key] - b[key]) / b[key] * 100
            what = "score" if key == "score" else "average FPS"
            if gain <= -1.5:
                mem_changed = (run.get("settings") or {}).get("mem_offset") != (base.get("settings") or {}).get("mem_offset") or \
                    (run.get("settings") or {}).get("vram_max") != (base.get("settings") or {}).get("vram_max")
                out.append(_issue("bad", f"Slower than {base.get('label', 'the baseline')} ({gain:+.1f}% {what})",
                                  "The tune is losing performance." + (" With a memory overclock this usually means the memory is past its limit and "
                                                                        "error correction is eating the gains." if mem_changed else ""),
                                  "Lower the memory offset first, then the core offset.", key))
            elif gain >= 1.5:
                out.append(_issue("good", f"{gain:+.1f}% {what} vs {base.get('label', 'baseline')}", "The tune is working.", None, key))
            else:
                out.append(_issue("info", f"About the same as {base.get('label', 'baseline')} ({gain:+.1f}%)",
                                  "Within run-to-run noise.", "Run a longer benchmark, or tune further.", key))
            if s.get("power_avg") and b.get("power_avg") and s.get("fps_avg") and b.get("fps_avg"):
                eff = (s["fps_avg"] / s["power_avg"]) / (b["fps_avg"] / b["power_avg"]) * 100 - 100
                if abs(eff) >= 3:
                    out.append(_issue("good" if eff > 0 else "info", f"Efficiency {eff:+.0f}% FPS per watt", "Compared with the baseline run.", None, "fps_per_watt"))

    out.sort(key=lambda i: LEVEL_ORDER[i["level"]])
    worst = out[0]["level"] if out else "good"
    verdict = {"bad": ("Problems found", "Fix the red items before trusting this tune."),
               "warn": ("Worth a look", "It works, but some things are holding the card back."),
               "info": ("Healthy", "Nothing to worry about - a few notes on how to get more."),
               "good": ("Healthy", "No problems found.")}[worst]
    return {"issues": out, "verdict": {"level": worst, "title": verdict[0], "text": verdict[1]}, "vendor": vendor}


def report(run_id=None, base_id=None) -> dict:
    rs = gputune.runs()
    if not rs:
        return {"runs": [], "run": None}
    run = next((r for r in rs if r["id"] == run_id), rs[-1])
    base = next((r for r in rs if r["id"] == base_id), None) if base_id else \
        next((r for r in reversed(rs) if r["label"] == "Before" and r["id"] != run["id"]), None)
    res = analyze(run, base)
    return {"runs": [{k: r.get(k) for k in ("id", "label", "source", "time")} for r in rs], "run": run, "base": base, **res}
