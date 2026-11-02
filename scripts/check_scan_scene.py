#!/usr/bin/env python
"""Check a converted scan: Go2 rests on the collision floor, and save overview and station views.

check_scan_scene.py <name>
"""
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mujoco
import numpy as np
from PIL import Image

from scout.config import load_config
from scout.sim_robot import SimRobot

name = sys.argv[1]
out = ROOT / "sim" / "generated" / f"scan_{name}"
cfg = load_config(out / "mission.yaml")
robot = SimRobot(cfg)

# Full physics for a moment: the unactuated robot must settle on the heightfield, not fall through.
m, d = robot.model, mujoco.MjData(robot.model)
ox, oy, _ = cfg["sim"]["origin"]
d.qpos[:] = robot.home
d.qpos[:3] = ox, oy, 0.32
mujoco.mj_forward(m, d)
for _ in range(int(0.8 / m.opt.timestep)):
    mujoco.mj_step(m, d)
rest_z = float(d.qpos[2])
contacts = int(d.ncon)

views = [Image.fromarray(robot.render("overview")).resize((640, 360))]
for st in cfg["stations"]:
    robot.true[:] = st["x"], st["y"], st["yaw"]
    robot._write_pose()
    views.append(Image.fromarray(robot.frame()).resize((640, 360)))
robot.close()
sheet = Image.new("RGB", (1280, 720))
for k, view in enumerate(views[:4]):
    sheet.paste(view, ((k % 2) * 640, (k // 2) * 360))
sheet.save(out / "views.png")
meta = json.loads((out / "meta.json").read_text())
meta["physics"] = {"rest_height_m": round(rest_z, 3), "contacts": contacts, "on_floor": bool(0.03 < rest_z < 0.4 and contacts > 0)}
(out / "meta.json").write_text(json.dumps(meta, indent=2))
print(name, meta["physics"], "free", meta["free_area_m2"], meta["route"])
