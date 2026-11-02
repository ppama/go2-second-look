#!/usr/bin/env python
"""Test heading estimation on real frames, using SLAM poses as ground truth. No robot needed.

align_real_check.py output/splat/sandbox
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from scout.align import estimate

root = Path(sys.argv[1])
cam = json.loads((root / "cameras.json").read_text())
fx = cam["K"][0][0]
frames = cam["frames"]
rng = np.random.default_rng(0)
poses = np.array([f["T_world_cam"] for f in frames])


def load(i):
    return np.array(Image.open(root / "images" / frames[i]["file"]))


rows = []
tries = 0
while len(rows) < 80 and tries < 4000:
    tries += 1
    a, b = rng.integers(0, len(frames), 2)
    relative = np.linalg.inv(poses[a]) @ poses[b]
    forward = relative[:3, 2]
    # Rotation about the camera's vertical axis. A positive value turns the view left.
    yaw = float(np.arctan2(-forward[0], forward[2]))
    move = float(np.linalg.norm(relative[:3, 3]))
    if not 0.03 < abs(yaw) < 0.45 or move > 0.45:
        continue
    result = estimate(load(a), load(b), fx)
    rows.append({"true_deg": np.degrees(yaw), "move_m": move, "matched": result is not None,
                 "est_deg": np.degrees(result["yaw"]) if result else None, "inliers": result["inliers"] if result else 0})
good = [r for r in rows if r["matched"]]
errors = np.array([abs(r["est_deg"] - r["true_deg"]) for r in good])
signs = np.array([r["est_deg"] * r["true_deg"] for r in good])
print(json.dumps({"pairs": len(rows), "matched": len(good), "median_error_deg": round(float(np.median(errors)), 2),
                  "p90_error_deg": round(float(np.percentile(errors, 90)), 2), "median_inliers": int(np.median([r["inliers"] for r in good])),
                  "sign_correct": round(float((signs > 0).mean()), 3), "median_true_turn_deg": round(float(np.median([abs(r["true_deg"]) for r in good])), 1)}))
(root / "align_check.json").write_text(json.dumps(rows, default=float))
