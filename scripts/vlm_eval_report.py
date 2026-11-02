#!/usr/bin/env python
"""Summarize vlm_eval.py against pixel difference and the detector on the same frames: vlm_eval_report.py [results.json]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "vlm_eval" / "results.json"
rows = json.loads(path.read_text())
LEVELS = ["base", "x2", "x4", "x8"]


def changed(row, method):
    if method in ("pixel", "detector"):
        return row[method]
    return row[method].get("changed")


def line(items, method):
    answered = [r for r in items if changed(r, method) is not None]
    pos = [r for r in answered if r["truth"] != "none"]
    neg = [r for r in answered if r["truth"] == "none"]
    return {"caught": f"{sum(changed(r, method) for r in pos)}/{len(pos)}",
            "false_alarms": f"{sum(changed(r, method) for r in neg)}/{len(neg)}", "failed": len(items) - len(answered)}


def kind_right(row):
    return row["truth"] in {c["type"] for c in row["compare"].get("changes", [])}


summary = {"levels": {}, "by_change": {}, "false_alarm_by_shift": {}}
for level in LEVELS:
    items = [r for r in rows if r["level"] == level]
    pos = [r for r in items if r["truth"] != "none" and r["compare"].get("changed")]
    summary["levels"][level] = {
        "stations": len(items), "vlm": line(items, "compare"), "pixel": line(items, "pixel"), "detector": line(items, "detector"),
        "type_right_when_caught": f"{sum(kind_right(r) for r in pos)}/{len(pos)}",
        "hazard_when_caught": f"{sum(bool(r['compare'].get('hazard')) for r in pos)}/{len(pos)}"}
base = [r for r in rows if r["level"] == "base"]
if any("single" in r for r in base):
    summary["single_frame_base"] = line(base, "single")
for kind in sorted({r["truth"] for r in rows} - {"none"}):
    summary["by_change"][kind] = {lv: line([r for r in rows if r["level"] == lv and r["truth"] == kind], "compare")["caught"] for lv in LEVELS}
neg = [r for r in rows if r["truth"] == "none" and "changed" in r["compare"]]
for low, high in ((0, 10), (10, 30), (30, 60), (60, 1000)):
    part = [r for r in neg if low <= r["stop_shift_cm"] < high]
    summary["false_alarm_by_shift"][f"{low}-{high}cm"] = f"{sum(r['compare']['changed'] for r in part)}/{len(part)}"
summary["false_alarm_by_station"] = {s: f"{sum(r['compare']['changed'] for r in neg if r['station'] == s)}/{sum(r['station'] == s for r in neg)}" for s in "ABC"}
(path.parent / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=1))
