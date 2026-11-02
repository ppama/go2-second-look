#!/usr/bin/env python
"""Score a local VLM on the rehearsal frames, the same pairs as pixel difference and the detector.

Needs logs/rehearsal from rehearsal.py. Resumable: finished pairs in the output are skipped.
vlm_eval.py [--levels base x2 x4 x8] [--out logs/vlm_eval/results.json] [--side-by-side]
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
from scout.vlm import OllamaVlm

REH = ROOT / "logs" / "rehearsal"


def load(path):
    return np.array(Image.open(path).convert("RGB"))


p = argparse.ArgumentParser()
p.add_argument("--levels", nargs="*", default=["base", "x2", "x4", "x8"])
p.add_argument("--out", default=str(ROOT / "logs" / "vlm_eval" / "results.json"))
p.add_argument("--side-by-side", action="store_true", help="send one composite picture instead of two images")
p.add_argument("--overlap", action="store_true", help="warp to the reference and compare the shared area only")
p.add_argument("--width", type=int, help="width of the picture sent to the model")
p.add_argument("--seeds", nargs="*", help="only these run seeds, for example 101 to tune and 202 to test")
args = p.parse_args()
out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
done = {(r["run"], r["station"]): r for r in json.loads(out.read_text())} if out.exists() else {}
cfg = load_config()["vlm"]
cfg["side_by_side"], cfg["overlap"] = args.side_by_side, args.overlap
cfg["ollama_width"] = args.width or cfg["ollama_width"]
vlm = OllamaVlm(cfg)
for row in json.loads((REH / "results.json").read_text()):
    key = (row["run"], row["station"])
    if row["level"] not in args.levels or key in done or (args.seeds and row["run"].rsplit("_", 1)[1] not in args.seeds):
        continue
    run = json.loads((REH / row["run"] / "run.json").read_text())
    st = run["stations"][row["station"]]
    before = load(REH / "ref" / "frames" / f"{row['station']}.jpg")
    after = load(REH / row["run"] / st["frame"])
    entry = {k: row[k] for k in ("level", "run", "station", "truth", "stop_shift_cm", "yaw_shift_deg", "pixel", "detector")}
    entry["compare"] = vlm.compare(before, after, st["name"])
    if row["level"] == "base" and not args.overlap:
        entry["single"] = vlm.single(after, st["name"])
    done[key] = entry
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(done.values()), indent=1))
    tmp.replace(out)
    print(key, row["truth"], entry["compare"].get("changed"), entry["compare"].get("summary", entry["compare"].get("error"))[:90], flush=True)

# Controls with known answers. Identical and same-scene pairs must not fire, swapped pairs must.
ref = {s: load(REH / "ref" / "frames" / f"{s}.jpg") for s in "ABC"}
controls = []
for s in "ABC":
    controls.append({"control": "identical", "pair": s, "want": False, **vlm.compare(ref[s], ref[s], f"station {s}")})
for a, b in (("A", "B"), ("B", "C"), ("C", "A")):
    controls.append({"control": "different_station", "pair": a + b, "want": True, **vlm.compare(ref[a], ref[b], f"station {a}")})
for row in (r for r in json.loads((REH / "results.json").read_text()) if r["level"] == "base" and r["truth"] != "none"):
    if row["station"] == "B" and len(controls) < 9 or row["station"] == "C" and len(controls) < 12:
        run = json.loads((REH / row["run"] / "run.json").read_text())
        after = load(REH / row["run"] / run["stations"][row["station"]]["frame"])
        controls.append({"control": "swapped", "pair": row["run"] + row["station"], "want": True, **vlm.compare(after, ref[row["station"]], "station")})
(out.parent / (out.stem + "_controls.json")).write_text(json.dumps(controls, indent=1))
# Declining a different-station pair is right: the views do not overlap.
print("controls right:", sum(c.get("changed") == c["want"] or (c["control"] == "different_station" and "error" in c) for c in controls), "of", len(controls))
print("calls", vlm.calls)
