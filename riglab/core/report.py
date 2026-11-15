"""Shareable system report (single HTML file) - handy when asking someone for help."""
from __future__ import annotations

import html
import time
from pathlib import Path

from .bench import load_history
from .config import APP_VERSION, app_dir

CSS = """body{font-family:Segoe UI,Arial,sans-serif;background:#0f1117;color:#e6e8ee;max-width:1000px;margin:auto;padding:24px}
h1{color:#5ee0ff}h2{border-bottom:1px solid #2a2f3d;padding-bottom:4px;margin-top:32px;color:#9aa4b8}
table{border-collapse:collapse;width:100%;margin:8px 0}td,th{padding:4px 10px;border-bottom:1px solid #1d2230;text-align:left;font-size:14px}
th{color:#9aa4b8;font-weight:600}.bad{color:#ff6b6b}.warn{color:#ffc35e}.good{color:#5eff9e}"""


def build(inventory: dict, hub, drives: list[dict]) -> Path:
    e = html.escape
    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>RigLab system report</title>"
             f"<style>{CSS}</style></head><body><h1>RigLab system report</h1>"
             f"<p>Generated {time.strftime('%Y-%m-%d %H:%M')} · RigLab {APP_VERSION}</p>"]
    for section, rows in inventory.items():
        parts.append(f"<h2>{e(section)}</h2><table>")
        for row in rows:
            for k, v in row.items():
                parts.append(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>")
            parts.append("<tr><td colspan=2></td></tr>")
        parts.append("</table>")

    if drives:
        parts.append("<h2>Drive health</h2><table><tr><th>Drive</th><th>Verdict</th><th>Temp</th>"
                     "<th>Wear</th><th>Power-on hours</th><th>Notes</th></tr>")
        for d in drives:
            cls = {"Good": "good", "Caution": "warn", "Bad": "bad"}.get(d["Verdict"], "")
            parts.append(f"<tr><td>{e(str(d.get('Name')))}</td><td class={cls}>{d['Verdict']}</td>"
                         f"<td>{d.get('Temp') or '—'}</td><td>{d.get('Wear') if d.get('Wear') is not None else '—'}</td>"
                         f"<td>{d.get('PowerOnHours') or '—'}</td><td>{e(d['Notes'])}</td></tr>")
        parts.append("</table>")

    parts.append("<h2>Sensors at time of report</h2><table><tr><th>Hardware</th><th>Sensor</th>"
                 "<th>Now</th><th>Min</th><th>Max</th></tr>")
    for s in sorted(hub.latest.sensors.values(), key=lambda s: (s.hardware, s.kind, s.name)):
        parts.append(f"<tr><td>{e(s.hardware)}</td><td>{e(s.kind)} · {e(s.name)}</td><td>{s.fmt()}</td>"
                     f"<td>{s.fmt(s.min) if s.min is not None else '—'}</td>"
                     f"<td>{s.fmt(s.max) if s.max is not None else '—'}</td></tr>")
    parts.append("</table>")

    hist = load_history()
    if hist:
        last = hist[-1]
        parts.append(f"<h2>Latest benchmark ({e(last['time'])})</h2><table>")
        for r in last["results"]:
            parts.append(f"<tr><th>{e(r['name'])}</th><td>{r['score']} {e(r['unit'])}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")

    out = app_dir() / "reports"
    out.mkdir(exist_ok=True)
    path = out / time.strftime("RigLab_report_%Y%m%d_%H%M.html")
    path.write_text("".join(parts), encoding="utf-8")
    return path
