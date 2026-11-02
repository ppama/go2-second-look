#!/usr/bin/env python
"""Run the trained detector on finished runs, on saved frames: detect_pairs.py logs/run1 logs/run2"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from scout.detector import Detector

detector = Detector(ROOT / "output" / "detector" / "change_net.pt")
rows = []
for folder in sys.argv[1:]:
    run = json.loads((Path(folder) / "run.json").read_text())
    for sid, st in run["stations"].items():
        before = np.array(Image.open(Path(run["reference"]) / "frames" / f"{sid}.jpg").convert("RGB"))
        after = np.array(Image.open(Path(folder) / st["frame"]).convert("RGB"))
        result = detector.compare(before, after, st["name"])
        truth = run["truth"][sid] != "none"
        rows.append((result["changed"], truth))
        print(Path(folder).name, sid, "truth", run["truth"][sid], "p", result["probability"], "OK" if result["changed"] == truth else "WRONG")
n = len(rows)
tp = sum(p and t for p, t in rows)
fp = sum(p and not t for p, t in rows)
fn = sum(t and not p for p, t in rows)
print(json.dumps({"n": n, "correct": n - fp - fn, "false_alarms": fp, "missed": fn}))
