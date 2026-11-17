"""'Explain my PC': the hardware inventory turned into plain English (pure, tested).

Input is the inventory from sysinfo.collect() ({section: [ {field: value} ]}). Each answer has a short title,
a plain sentence or two, a traffic-light state where it helps, and the technical facts for "Show details".
"""
from __future__ import annotations

import re
from datetime import date


def _first(sections, name):
    rows = sections.get(name) or []
    return rows[0] if rows else {}


def _num(text, default=None):
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1)) if m else default


def _gb(text):
    """'32.0 GB' / '1.8 TB' / '512 MB' -> GB."""
    v = _num(text)
    if v is None:
        return None
    t = str(text).upper()
    return v * 1024 if "TB" in t else v / 1024 if "MB" in t else v


INTEGRATED = re.compile(r"(uhd|iris|hd graphics|radeon\(tm\) graphics$|radeon graphics$|vega \d+ graphics|microsoft basic)", re.I)


def explain(sections: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []

    cpu = _first(sections, "Processor")
    if cpu.get("Model"):
        cores = threads = None
        m = re.match(r"\s*(\d+)\s*/\s*(\d+)", str(cpu.get("Cores / Threads") or ""))
        if m:
            cores, threads = int(m.group(1)), int(m.group(2))
        if cores is None:
            verdict = ""
        elif cores >= 8:
            verdict = " That's plenty for gaming, streaming and heavy apps."
        elif cores >= 6:
            verdict = " That's good for gaming and everyday use."
        elif cores >= 4:
            verdict = " That's fine for everyday use and lighter games."
        else:
            verdict = " That's enough for simple tasks, but heavy apps and new games may feel slow."
        jobs = f" It has {cores} cores, so it can work on {cores} jobs at once" + (f" ({threads} with its extra threads)." if threads and threads != cores else ".") if cores else ""
        out.append({"id": "cpu", "icon": "cpu", "title": "Processor (the brain)", "state": "none",
                    "say": f"Your processor is an {cpu['Model']}.{jobs}{verdict}",
                    "details": _lines(cpu)})

    gpus = [g for g in sections.get("Graphics") or [] if g.get("Model")]
    if gpus:
        main = next((g for g in gpus if not INTEGRATED.search(g["Model"])), gpus[0])
        integrated = bool(INTEGRATED.search(main["Model"]))
        say = (f"Your graphics are built into the processor ({main['Model']}). That's fine for everyday use, videos and light games."
               if integrated else
               f"Your graphics card is an {main['Model']}. It draws everything you see, and it's what matters most for games.")
        if len(gpus) > 1:
            say += f" Your PC also has {len(gpus) - 1} other graphics chip{'s' if len(gpus) > 2 else ''}."
        out.append({"id": "gpu", "icon": "gpu", "title": "Graphics", "state": "none", "say": say,
                    "details": "\n".join(_lines(g) for g in gpus)})

    mem = _first(sections, "Memory")
    total = _gb(mem.get("Total"))
    if total:
        n = round(total)
        if n < 8:
            verdict, st = "That's not much - your PC may slow down with a few apps open. Adding more memory would help a lot.", "warn"
        elif n < 16:
            verdict, st = "That's enough for everyday use. 16 GB is better for gaming.", "good"
        elif n < 32:
            verdict, st = "That's plenty for gaming and most work.", "good"
        else:
            verdict, st = "That's lots - great for gaming, streaming and video editing.", "good"
        say = f"Your PC has {n} GB of memory (RAM). Memory holds what you're working on right now. {verdict}"
        rated, running = _num(mem.get("Rated speed")), _num(mem.get("Running speed"))
        if rated and running and running < rated * 0.9:      # e.g. DDR5 at 4800 instead of 6000 = XMP/EXPO off
            say += (f" Your memory is running at {int(running)} instead of its full {int(rated)} speed. "
                    "Turning on its XMP/EXPO setting in your BIOS fixes this (see Overclocking in Advanced view).")
            st = "warn"
        out.append({"id": "memory", "icon": "ram", "title": "Memory", "state": st, "say": say, "details": _lines(mem)})

    drives = [d for d in sections.get("Storage") or [] if d.get("Drive")]
    vols = [d for d in sections.get("Storage") or [] if d.get("Volume")]
    if drives:
        ssd = [d for d in drives if "SSD" in str(d.get("Type", "")).upper() or "NVME" in str(d.get("Type", "")).upper()]
        hdd = [d for d in drives if "HDD" in str(d.get("Type", "")).upper()]
        if ssd and not hdd:
            say, st = ("Your drives are SSDs. They're fast, so Windows starts quickly and games load fast." if len(ssd) > 1
                       else "Your drive is an SSD. It's fast, so Windows starts quickly and games load fast."), "good"
        elif hdd and not ssd:
            say, st = "Your drive is a hard disk. Hard disks are much slower than SSDs - an SSD would make your PC feel a lot faster.", "warn"
        else:
            say, st = f"Your PC has {len(ssd)} SSD{'s' if len(ssd) != 1 else ''} (fast) and {len(hdd)} hard disk{'s' if len(hdd) != 1 else ''} (slower, good for storing big files).", "good"
        for v in vols:
            m = re.search(r"\((\d+)%\)", str(v.get("Used", "")))
            if m and str(v.get("Volume", "")).upper().startswith("C"):
                pct = int(m.group(1))
                say += f" Your main drive is {pct}% full."
                if pct >= 90:
                    st = "warn"
                    say += " That's nearly full - a clean-up would help."
        out.append({"id": "storage", "icon": "disk", "title": "Storage", "state": st, "say": say,
                    "details": "\n".join(_lines(d) for d in drives + vols)})

    shows = [g.get("Display") for g in gpus if g.get("Display") and g.get("Display") != "—"]
    mons = [m for m in sections.get("Displays") or [] if m.get("Monitor")]
    if shows or mons:
        say = f"You have {len(mons) or len(shows)} screen{'s' if (len(mons) or len(shows)) != 1 else ''}."
        m = re.match(r"(\d+)x(\d+) @ (\d+)", shows[0]) if shows else None
        if m:
            w, h, hz = (int(x) for x in m.groups())
            say += f" Your main screen shows {w} × {h} pixels and updates {hz} times a second ({hz} Hz)."
            say += " That's smooth - great for games." if hz >= 120 else " That's standard. Screens at 120 Hz or more feel smoother in games." if hz >= 50 else ""
        out.append({"id": "display", "icon": "monitor", "title": "Screens", "state": "none", "say": say,
                    "details": "\n".join([_lines(x) for x in mons] + [f"Graphics output: {x}" for x in shows])})

    osr = _first(sections, "System")
    if osr.get("OS"):
        out.append({"id": "windows", "icon": "sys", "title": "Windows", "state": "none",
                    "say": f"You're running {osr['OS'].replace('Microsoft ', '')}.", "details": _lines(osr)})

    board = _first(sections, "Motherboard")
    bios = next((b for b in sections.get("Motherboard") or [] if b.get("BIOS")), {})
    if board.get("Model"):
        say = f"Everything plugs into your motherboard, a {board.get('Manufacturer', '').replace(' COMPUTER INC.', '').replace('ASUSTeK', 'ASUS').strip()} {board['Model']}."
        st = "none"
        y = _num(str(bios.get("BIOS date", ""))[:4])
        if y and today.year - int(y) >= 3:
            say += f" Its BIOS (the built-in settings program) is from {int(y)}. A newer one may fix bugs and support newer parts."
            st = "warn"
        out.append({"id": "board", "icon": "board", "title": "Motherboard", "state": st, "say": say,
                    "details": _lines(board) + ("\n" + _lines(bios) if bios else "")})

    nets = [n for n in sections.get("Network") or [] if n.get("Adapter")]
    up = [n for n in nets if "Mbps" in str(n.get("Link", ""))]
    if nets:
        if up:
            sp = int(_num(up[0]["Link"], 0) or 0)
            say = f"You're connected through {up[0]['Adapter']} at {sp:,} megabits a second."
            if "wi-fi" in up[0]["Adapter"].lower() or "wireless" in up[0]["Adapter"].lower():
                say += " That's Wi-Fi - a cable is usually steadier for online games."
        else:
            say = "None of your network adapters is connected right now."
        out.append({"id": "network", "icon": "net", "title": "Network", "state": "none" if up else "warn", "say": say,
                    "details": "\n".join(_lines(n) for n in nets)})
    return out


def _lines(row: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in (row or {}).items() if v not in (None, ""))
