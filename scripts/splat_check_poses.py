#!/usr/bin/env python
"""Project the coloured cloud into real frames, to prove the poses are right before training."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

out = Path(sys.argv[1])
cam = json.loads((out / "cameras.json").read_text())
data = np.load(out / "cloud.npz")
points, colors = data["points"], data["colors"]
K = np.array(cam["K"])
rows, errors = [], []
picks = np.linspace(0, len(cam["frames"]) - 1, 12).astype(int)
for n, idx in enumerate(picks):
    frame = cam["frames"][idx]
    photo = np.array(Image.open(out / "images" / frame["file"]))
    w2c = np.linalg.inv(np.array(frame["T_world_cam"]))
    p = points @ w2c[:3, :3].T + w2c[:3, 3]
    front = p[:, 2] > 0.2
    uv = p[front] @ K.T
    u, v = (uv[:, 0] / uv[:, 2]).astype(int), (uv[:, 1] / uv[:, 2]).astype(int)
    inside = (u >= 0) & (u < 1280) & (v >= 0) & (v < 720)
    depth, c = p[front][inside, 2], colors[front][inside]
    u, v = u[inside], v[inside]
    order = np.argsort(-depth)
    render = np.zeros((720, 1280, 3), np.uint8)
    for du in (0, 1, 2):
        for dv in (0, 1, 2):
            render[np.minimum(v[order] + dv, 719), np.minimum(u[order] + du, 1279)] = c[order]
    mask = render.sum(2) > 0
    errors.append(float(np.abs(render[mask].astype(float) - photo[mask]).mean()) if mask.any() else 999)
    if n in (2, 5, 8):
        rows.append(np.hstack([photo, render]))
Image.fromarray(np.vstack(rows)).resize((1280, 1080)).save(out / "pose_check.png")
print("mean colour error per frame", [round(e, 1) for e in errors])
