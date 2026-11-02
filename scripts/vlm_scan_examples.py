#!/usr/bin/env python
"""VLM examples in a real2sim scan room: three clean patrols and three with a box added at station B.

Saves frames only; run revlm.py on the runs for VLM results. vlm_scan_examples.py <name>
"""
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml

name = sys.argv[1]
base = ROOT / "sim" / "generated" / f"scan_{name}"
cfg = yaml.safe_load((base / "mission.yaml").read_text())
ox, oy, oyaw = cfg["sim"]["origin"]
st = next(s for s in cfg["stations"] if s["id"] == "B")
heading, ahead = oyaw + st["yaw"], 1.3
x = ox + math.cos(oyaw) * st["x"] - math.sin(oyaw) * st["y"] + ahead * math.cos(heading)
y = oy + math.sin(oyaw) * st["x"] + math.cos(oyaw) * st["y"] + ahead * math.sin(heading)
box = (f'<body pos="{x:.3f} {y:.3f} 0.2"><geom type="box" size="0.18 0.18 0.2" rgba="0.9 0.35 0.05 1" '
       'contype="0" conaffinity="0"/></body>\n  </worldbody>')
scene = (ROOT / "sim" / f"scan_{name}.xml").read_text().replace("</worldbody>", box)
(ROOT / "sim" / f"scan_{name}_box.xml").write_text(scene)
box_cfg = dict(cfg)
box_cfg["sim"] = {**cfg["sim"], "scene": f"scan_{name}_box.xml"}
(base / "mission_box.yaml").write_text(yaml.safe_dump(box_cfg))


def patrol(run, config, seed, phase="after"):
    cmd = [sys.executable, "scripts/run_patrol.py", "--backend", "sim", "--config", str(config), "--phase", phase,
           "--run", run, "--seed", str(seed), "--vlm", "none"]
    if phase == "after":
        cmd += ["--reference", f"logs/{name}_ref"]
    subprocess.run(cmd, check=True, cwd=ROOT)


patrol(f"{name}_ref", base / "mission.yaml", 0, "before")
for seed in (11, 12, 13):
    patrol(f"{name}_none_{seed}", base / "mission.yaml", seed)
    run = f"{name}_box_{seed}"
    patrol(run, base / "mission_box.yaml", seed)
    path = ROOT / "logs" / run / "run.json"
    data = json.loads(path.read_text())
    data["truth"]["B"] = "added"
    path.write_text(json.dumps(data, indent=2))
