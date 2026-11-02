#!/usr/bin/env python
"""Final survey log as survey.md and survey.png: make_survey.py logs/run"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

run_dir = Path(sys.argv[1])
run = json.loads((run_dir / "run.json").read_text())


def font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def status(result):
    if "error" in result:
        return "NO RESULT"
    if result.get("hazard"):
        return "HAZARD"
    return "CHANGED" if result.get("changed") else "No change"


sim = run.get("backend") == "sim"
title = "Site survey log" + (" (simulation)" if sim else "")
lines = [f"# {title}", "", f"Run status: {run['status']}. VLM: {run.get('vlm')}, model: {run.get('model')}.", "",
         "| Station | Result | Summary | Image |", "|---|---|---|---|"]
THUMB, ROW = (284, 160), 176
sheet = Image.new("RGB", (1280, 100 + ROW * len(run["stations"]) + 20), "#111418")
draw = ImageDraw.Draw(sheet)
draw.text((30, 28), title, fill="white", font=font(36))
for i, (sid, st) in enumerate(run["stations"].items()):
    result = st.get("compare", {})
    summary = result.get("summary", result.get("error", ""))
    lines.append(f"| {sid} {st['name']} | {status(result)} | {summary[:160]} | {st['frame']} |")
    y = 100 + i * ROW
    sheet.paste(Image.open(run_dir / st["frame"]).convert("RGB").resize(THUMB), (30, y))
    colour = "#ff6b5e" if status(result) in ("HAZARD", "NO RESULT") else "#ffc94d" if status(result) == "CHANGED" else "#6ee7a0"
    draw.text((340, y + 8), f"{sid}  {st['name']}", fill="white", font=font(26))
    draw.text((340, y + 48), status(result), fill=colour, font=font(26))
    draw.text((340, y + 92), summary[:78], fill="#d0d4da", font=font(20))
(run_dir / "survey.md").write_text("\n".join(lines) + "\n")
sheet.save(run_dir / "survey.png")
print("saved", run_dir / "survey.md", run_dir / "survey.png")
