#!/usr/bin/env python
"""Fallback simulation video. Every result on screen is read from the run logs.

make_sim_demo.py OUT.mp4 --reference logs/ref --after logs/after
"""
import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from scout.config import load_config
from scout.sim_robot import SimRobot
from scout.videokit import BOLD, FIT, REGULAR, SIZE, caption, concat, ffmpeg, font, slide, still


def patrol_clip(source, caption_png, out):
    """2x clip with a caption bar over the bottom of the frame."""
    ffmpeg("-i", str(source), "-i", str(caption_png), "-filter_complex",
           f"[0:v]setpts=0.5*PTS,{FIT}[v];[v][1:v]overlay=0:{SIZE[1] - 56}", "-an", str(out))


def scene_change(path, changes, cfg):
    """Wide views of the site before and after the changes, with the robot off to the side."""
    panels = []
    for active in ([], changes):
        robot = SimRobot(cfg, active)
        robot.true[:] = (-1.2, 0.3, 0)
        robot._write_pose()
        panels.append(Image.fromarray(robot.render("overview")).resize((640, 360)))
        robot.close()
    img = Image.new("RGB", SIZE, "#111418")
    draw = ImageDraw.Draw(img)
    draw.text((640, 110), "The site changes between patrols", fill="white", font=font(BOLD, 40), anchor="mm")
    img.paste(panels[0], (0, 180))
    img.paste(panels[1], (640, 180))
    draw.text((320, 570), "Before", fill="#d0d4da", font=font(REGULAR, 28), anchor="mm")
    draw.text((960, 570), "After", fill="#d0d4da", font=font(REGULAR, 28), anchor="mm")
    draw.text((640, 640), "Changed in the simulation. Scout is not told what changed.", fill="#ffc94d", font=font(REGULAR, 26), anchor="mm")
    img.save(path)


def verdict(result):
    if "changed" not in result:
        return "no result"
    return "changed" if result["changed"] else "no change"


p = argparse.ArgumentParser()
p.add_argument("out")
p.add_argument("--reference", required=True)
p.add_argument("--after", required=True)
args = p.parse_args()

ref, after = Path(args.reference), Path(args.after)
run = json.loads((after / "run.json").read_text())
cfg = load_config()
stations = run["stations"]
true_err = math.hypot(*run["true_final_pose"][:2]) * 100
odom_err = math.hypot(*run["final_odom_pose"][:2]) * 100
right = sum(st["compare"].get("changed") == (run["truth"][sid] != "none") for sid, st in stations.items())
baseline = [(sid, st) for sid, st in stations.items() if "single" in st]

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    parts = []

    def add_still(name, seconds):
        out = tmp / f"{name}.mp4"
        still(tmp / f"{name}.png", seconds, out)
        parts.append(out)

    slide(tmp / "title.png", "Second Look", ["A simulated Unitree Go2 inspects a site twice", "and reports what changed.", "",
                                             "Simulation in MuJoCo. Patrol footage at 2x speed."])
    add_still("title", 5)
    slide(tmp / "idea.png", "Why look twice?", ["Rocks move, equipment falls, and materials go missing.",
                                                "A map of a work site goes out of date.", "",
                                                "Mission: save a view at each station, return later,",
                                                "and compare old and new views with a vision language model."])
    add_still("idea", 7)
    caption(tmp / "cap1.png", "Patrol 1: saving a reference view at stations A, B and C. Simulation, 2x.")
    parts.append(tmp / "p1.mp4")
    patrol_clip(ref / "patrol.mp4", tmp / "cap1.png", tmp / "p1.mp4")
    scene_change(tmp / "change.png", run["changes"], cfg)
    add_still("change", 6)
    caption(tmp / "cap2.png", "Patrol 2: the same route, with simulated drift. Simulation, 2x.")
    parts.append(tmp / "p2.mp4")
    patrol_clip(after / "patrol.mp4", tmp / "cap2.png", tmp / "p2.mp4")
    for sid in stations:
        out = tmp / f"card_{sid}.mp4"
        still(after / "cards" / f"{sid}.png", 6, out)
        parts.append(out)
    if baseline:
        lines = ["The model saw only the current view, with no reference:", ""]
        for sid, st in baseline:
            lines += [f"Station {sid}, true state: {run['truth'][sid]}",
                      f"    Single frame: {verdict(st['single'])}.   Before/after: {verdict(st['compare'])}."]
        slide(tmp / "base.png", "Why keep a reference?", lines)
        add_still("base", 7)
    still(after / "survey.png", 6, tmp / "survey.mp4")
    parts.append(tmp / "survey.mp4")
    slide(tmp / "end.png", "Result of this simulated run", [
        f"Before/after: {right} of {len(stations)} stations correct, on this one run.",
        f"Return error: {true_err:.0f} cm true, while odometry reported {odom_err:.0f} cm.",
        "Drift is set by assumed simulation values, not measured.", "",
        "The VLM reads images only. It cannot command the robot.",
        "Intended use: repeat site inspection. Not shown on a real site."])
    add_still("end", 8)
    concat(parts, tmp / "list.txt", args.out)
print("saved", args.out)
