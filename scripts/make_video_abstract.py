#!/usr/bin/env python
"""Conference-style video abstract from the room clips, robot camera and logged results.

make_video_abstract.py OUT.mp4 --room-ref go2_run1.mp4 --room-after go2_run2.mp4
Every number comes from the logs and docs/VLM_EVAL.md. Clips are silent and shown at 2x.
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from scout.videokit import BOLD, FIT, REGULAR, SIZE, caption, concat, ffmpeg, font, slide, still

SPEED = 2
INK, MUTED, BG, ACCENT = "white", "#d0d4da", "#111418", "#4ea1ff"


def clip(room, camera, start, end, camera_start, label, out):
    cap = out.with_suffix(".png")
    caption(cap, label)
    graph = (f"[0:v]setpts=PTS/{SPEED},{FIT}[v];[2:v]setpts=PTS/{SPEED},scale=420:-2,drawbox=c=white:t=3[c];"
             f"[v][c]overlay=W-w-16:16[a];[a][1:v]overlay=0:{SIZE[1] - 56}[o]")
    ffmpeg("-ss", str(start), "-t", str(end - start), "-i", str(room), "-i", str(cap), "-ss", str(camera_start), "-t", str(end - start),
           "-i", str(camera), "-filter_complex", graph, "-map", "[o]", "-an", str(out))


def diagram(path):
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    d.text((90, 70), "Method", fill=INK, font=font(BOLD, 48))
    boxes = [("Go2 patrol", "fixed stations"), ("Saved views", "reference, now"), ("Local VLM", "compare"), ("Survey log", "what changed")]
    w, h, gap, y = 230, 130, 50, 220
    for k, (top, sub) in enumerate(boxes):
        x = 75 + k * (w + gap)
        d.rounded_rectangle((x, y, x + w, y + h), 14, outline=ACCENT, width=3)
        d.text((x + 20, y + 32), top, fill=INK, font=font(BOLD, 28))
        d.text((x + 20, y + 76), sub, fill=MUTED, font=font(REGULAR, 22))
        if k < 3:
            d.line((x + w + 6, y + h / 2, x + w + gap - 8, y + h / 2), fill=MUTED, width=4)
            d.polygon([(x + w + gap - 6, y + h / 2), (x + w + gap - 20, y + h / 2 - 9), (x + w + gap - 20, y + h / 2 + 9)], fill=MUTED)
    for k, line in enumerate(["Odometry drives. The robot stops at each station and saves a view.",
                              "The VLM reads saved images only. It cannot command the robot.",
                              "Reference and current views go in as one side-by-side picture."]):
        d.text((90, 420 + k * 54), line, fill=MUTED, font=font(REGULAR, 28))
    img.save(path)


def table(path, heading, note, header, rows):
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    d.text((90, 70), heading, fill=INK, font=font(BOLD, 44))
    d.text((90, 136), note, fill=MUTED, font=font(REGULAR, 25))
    xs = [90, 330, 590, 880]
    for k, row in enumerate([header] + rows):
        y = 205 + k * 62
        for x, cell in zip(xs, row):
            d.text((x, y), cell, fill=INK if k else ACCENT, font=font(BOLD if k == 0 or x == 330 else REGULAR, 29))
    d.line((90, 252, 1190, 252), fill="#555", width=2)
    img.save(path)


def split(ref, after, out):
    a, b = Image.open(ref).convert("RGB").resize((640, 360)), Image.open(after).convert("RGB").resize((640, 360))
    img = Image.new("RGB", SIZE, BG)
    img.paste(a, (0, 120))
    img.paste(b, (640, 120))
    d = ImageDraw.Draw(img)
    d.text((40, 40), "The scene is changed by hand", fill=INK, font=font(BOLD, 40))
    d.text((40, 500), "Before", fill=ACCENT, font=font(BOLD, 28))
    d.text((680, 500), "After", fill=ACCENT, font=font(BOLD, 28))
    d.text((40, 570), "Station A: a rock added.   Station B: rock moved.   Station C: object removed.", fill=MUTED, font=font(REGULAR, 28))
    d.text((40, 620), "The robot is not told what changed.", fill=MUTED, font=font(REGULAR, 28))
    img.save(out)


p = argparse.ArgumentParser()
p.add_argument("out")
p.add_argument("--room-ref", required=True)
p.add_argument("--room-after", required=True)
args = p.parse_args()
logs = ROOT / "logs"
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    parts = []

    def add(name, seconds, make=None):
        png = tmp / f"{name}.png"
        if make:
            make(png)
        out = tmp / f"{name}.mp4"
        still(png, seconds, out)
        parts.append(out)

    add("title", 5, lambda f: slide(f, "Second Look", ["Finding what changed at a site,", "with a Unitree Go2 and a vision language model.", "", "Video abstract. Robot footage is real and shown at 2x."]))
    add("problem", 7, lambda f: slide(f, "Sites change between visits", ["Maps of a work site go out of date.", "A robot can return to the same views and look again.", "", "Can it tell a real change from a small stop error?"]))
    add("method", 9, diagram)
    parts.append(tmp / "p1.mp4")
    clip(args.room_ref, logs / "go2_ref2" / "camera.mp4", 0, 44, 8, "Patrol 1: save a reference view at three stations. Real robot, 2x. Inset: robot camera.", tmp / "p1.mp4")
    ffmpeg("-ss", "50", "-i", args.room_ref, "-frames:v", "1", str(tmp / "room_a.png"))
    ffmpeg("-ss", "55", "-i", args.room_after, "-frames:v", "1", str(tmp / "room_b.png"))
    add("change", 7, lambda f: split(tmp / "room_a.png", tmp / "room_b.png", f))
    parts.append(tmp / "p2.mp4")
    clip(args.room_after, logs / "go2_1" / "camera.mp4", 3, 52, 2.5, "Patrol 2: same route, changed scene. Real robot, 2x. Inset: robot camera.", tmp / "p2.mp4")
    for sid in "ABC":
        out = tmp / f"card_{sid}.mp4"
        still(logs / "go2_1" / "cards" / f"{sid}.png", 5, out)
        parts.append(out)
    out = tmp / "card_control.mp4"
    still(logs / "go2_2" / "cards" / "B.png", 4, out)
    parts.append(out)
    add("real", 9, lambda f: slide(f, "Real robot results", [
        "Before/after: 6 of 6 stations right. 3 caught, 0 of 3 false alarms.",
        "Single image, no reference: missed all 3 changes.",
        "Known-answer image pairs: 8 of 8 right.",
        "Change type exact at 1 of 3. Hazard flag set at 0 of 3.",
        "Model: qwen3.6, local. One changed patrol and one control."]))
    add("finding", 9, lambda f: slide(f, "Key finding, in simulation", [
        "Two separate images: 12 of 12 changes caught at base drift.",
        "But known-answer pairs were only 7 of 12 right:",
        "the model was mostly answering by station.", "",
        "One side-by-side picture: known-answer pairs 12 of 12."]))
    add("sim", 8, lambda f: table(f, "Simulation: false alarms", "18 unseen MuJoCo stations per level. All methods caught 6 of 6. Drift values are assumed.",
                                  ["Drift", "VLM", "Trained detector", "Pixel difference"],
                                  [["Base", "3 of 12", "5 of 12", "12 of 12"], ["x2", "7 of 12", "6 of 12", "12 of 12"],
                                   ["x4", "9 of 12", "11 of 12", "12 of 12"], ["x8", "9 of 12", "11 of 12", "12 of 12"]]))
    out = tmp / "sim_examples.mp4"
    still(ROOT / "docs" / "images" / "sim_results_en.png", 8, out)
    parts.append(out)
    add("limits", 8, lambda f: slide(f, "Limits", [
        "Small sample, from one lab mock-up.",
        "VLM results were computed after the patrols, from saved frames.",
        "Return error about 0.1 m by odometry. True error not measured.",
        "Hand-held remote stop was not tested. Robot on a cable.",
        "Lunar site inspection is the intended use, not a demonstrated result."]))
    add("end", 4, lambda f: slide(f, "Second Look", ["Inference-only AI. The VLM reads images and cannot command the robot."]))
    concat(parts, tmp / "list.txt", args.out)
print("saved", args.out)
