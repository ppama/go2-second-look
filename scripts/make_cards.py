#!/usr/bin/env python
"""Before/after split-screen images with the logged VLM result: make_cards.py logs/run [--no-boxes]"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 640, 360


def font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


run_dir = Path(sys.argv[1])
run = json.loads((run_dir / "run.json").read_text())
out = run_dir / "cards"
out.mkdir(exist_ok=True)
for sid, st in run["stations"].items():
    after = Image.open(run_dir / st["frame"]).convert("RGB").resize((W, H))
    before = Image.open(Path(run["reference"]) / "frames" / f"{sid}.jpg").convert("RGB").resize((W, H))
    card = Image.new("RGB", (W * 2, H + 80), "black")
    card.paste(before, (0, 0))
    card.paste(after, (W, 0))
    draw = ImageDraw.Draw(card)
    result = st.get("compare", {})
    for c in result.get("changes", []):
        if c.get("box_2d") and "--no-boxes" not in sys.argv:
            y0, x0, y1, x1 = [v / 1000 for v in c["box_2d"]]
            draw.rectangle((W + x0 * W, y0 * H, W + x1 * W, y1 * H), outline="red", width=4)
    tag = "MOCK, not a VLM result: " if run.get("vlm") == "mock" else ""
    if run.get("backend") == "sim":
        tag = "SIMULATION. " + tag
    draw.text((10, H + 8), f"Station {sid}: {st['name']}    BEFORE | NOW", fill="white", font=font(24))
    draw.text((10, H + 44), tag + result.get("summary", result.get("error", ""))[:100], fill="yellow", font=font(21))
    card.save(out / f"{sid}.png")
print("saved", out)
