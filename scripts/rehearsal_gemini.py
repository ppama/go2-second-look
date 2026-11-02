#!/usr/bin/env python
"""Spend a few Robotics ER calls to find how much drift the comparison tolerates."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from scout.config import load_config
from scout.vlm import GeminiVlm

OUT = ROOT / "logs" / "rehearsal"
rows = json.loads((OUT / "results.json").read_text())


def pick(level, station, truth):
    items = [r for r in rows if r["level"] == level and r["station"] == station and r["truth"] == truth]
    return sorted(items, key=lambda r: r["stop_shift_cm"])[len(items) // 2]


cases = [pick("x2", "B", "none"), pick("x2", "C", "none"), pick("x2", "B", "fallen"), pick("x4", "B", "none"), pick("x4", "C", "none"), pick("x4", "C", "removed")]
vlm = GeminiVlm(load_config()["vlm"])
load = lambda p: np.array(Image.open(p).convert("RGB"))
out = []
for r in cases:
    result = vlm.compare(load(OUT / "ref/frames" / f"{r['station']}.jpg"), load(OUT / r["run"] / "frames" / f"{r['station']}.jpg"), f"station {r['station']}")
    row = {k: r[k] for k in ("level", "station", "truth", "run")}
    row.update(shift_cm=round(r["stop_shift_cm"], 1), yaw_deg=round(r["yaw_shift_deg"], 1), changed=result.get("changed"), error=str(result.get("error", ""))[:90], summary=result.get("summary", "")[:110])
    out.append(row)
    print(row, flush=True)
    if "429" in row["error"]:
        print("rate limited, stopping")
        break
(OUT / "gemini_drift.json").write_text(json.dumps(out, indent=2))
print("calls", vlm.calls)
