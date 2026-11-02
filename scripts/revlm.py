#!/usr/bin/env python
"""Run the VLM on a finished run's saved frames, without the robot.

Fills failed or missing results only, so it spends no calls on stations that are done.
revlm.py logs/run [--mode compare|single] [--stations B C] [--vlm mock]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from scout.config import load_config
from scout.vlm import GeminiVlm, MockVlm, OllamaVlm


def load(path):
    return np.array(Image.open(path).convert("RGB"))


p = argparse.ArgumentParser()
p.add_argument("run")
p.add_argument("--mode", choices=["compare", "single"], default="compare")
p.add_argument("--stations", nargs="*")
p.add_argument("--vlm", choices=["gemini", "ollama", "mock"], default="gemini")
args = p.parse_args()

run_dir = Path(args.run)
run = json.loads((run_dir / "run.json").read_text())
cfg = load_config()
vlm = {"gemini": GeminiVlm, "ollama": OllamaVlm}[args.vlm](cfg["vlm"]) if args.vlm != "mock" else MockVlm()
run["vlm"], run["model"] = vlm.backend, getattr(vlm, "model", None) or (cfg["vlm"]["model"] if args.vlm == "gemini" else None)

for sid, st in run["stations"].items():
    done = "changed" in st.get(args.mode, {})
    if done or (args.stations and sid not in args.stations):
        continue
    after = load(run_dir / st["frame"])
    if args.mode == "compare":
        before = load(Path(run["reference"]) / "frames" / f"{sid}.jpg")
        result = vlm.compare(before, after, st["name"])
    else:
        result = vlm.single(after, st["name"])
    st[args.mode] = result
    print(sid, result.get("summary", result.get("error")))
    tmp = run_dir / "run.json.tmp"
    tmp.write_text(json.dumps(run, indent=2))
    tmp.replace(run_dir / "run.json")
    if "429" in result.get("error", ""):
        print("rate limited, stopping")
        break
print("VLM calls:", vlm.calls)
