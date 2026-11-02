#!/usr/bin/env python
"""Figure of MuJoCo before/after pairs with the VLM's reply: docs/images/sim_results_{ja,en}.png"""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
REH = ROOT / "logs" / "rehearsal"
FONT = subprocess.run(["fc-match", "-f", "%{file}", "Noto Sans CJK JP"], capture_output=True, text=True).stdout
PICKS = [("fallen", "B"), ("removed", "C"), ("added", "B"), ("none", "C")]
WORDS = {"ja": {"fallen": "正解: 転倒", "removed": "正解: 除去", "added": "正解: 追加", "none": "正解: 変化なし", "ref": "基準", "now": "現在"},
         "en": {"fallen": "Truth: fallen", "removed": "Truth: removed", "added": "Truth: added", "none": "Truth: no change", "ref": "Reference", "now": "Now"}}
rows = [r for r in json.loads((ROOT / "logs" / "vlm_eval" / "final_test.json").read_text()) if r["level"] == "base"]


def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        if draw.textlength(f"{line} {word}", font=font) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


for lang, words in WORDS.items():
    img = Image.new("RGB", (1280, 720), "#111418")
    d = ImageDraw.Draw(img)
    small, bold = ImageFont.truetype(FONT, 18, index=0), ImageFont.truetype(FONT, 21, index=0)
    for k, (truth, station) in enumerate(PICKS):
        row = next(r for r in rows if r["truth"] == truth and r["station"] == station and r["compare"]["changed"] == (truth != "none"))
        run = json.loads((REH / row["run"] / "run.json").read_text())
        x, y = (k % 2) * 640, (k // 2) * 360
        for j, path in enumerate((REH / "ref" / "frames" / f"{station}.jpg", REH / row["run"] / run["stations"][station]["frame"])):
            img.paste(Image.open(path).convert("RGB").resize((312, 176)), (x + 6 + j * 316, y + 6))
            d.text((x + 12 + j * 316, y + 8), words["ref" if j == 0 else "now"], fill="white", font=small, stroke_width=2, stroke_fill="black")
        d.text((x + 8, y + 186), f"{station}  {words[truth]}", fill="#4ea1ff", font=bold)
        for n, line in enumerate(wrap(d, row["compare"]["summary"], small, 620)[:4]):
            d.text((x + 8, y + 218 + n * 25), line, fill="#ffe08a", font=small)
    out = ROOT / "docs" / "images" / f"sim_results_{lang}.png"
    out.parent.mkdir(exist_ok=True)
    img.save(out)
    print("saved", out)
