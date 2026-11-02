#!/usr/bin/env python
"""Build the real-robot video from filmed clips and logged results.

Every result comes from run.json. State the return error with --return-note.
Run make_cards.py and make_survey.py first.

make_real_demo.py OUT.mp4 --reference logs/go2_ref --after logs/go2_1 --return-note "..." \\
    --patrol1 p1.mp4 --patrol2 p2.mp4 [--change change.mp4] [--control "..."] [--intro intro.mp4] [--speed 2]
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scout.videokit import FIT, SIZE, caption, concat, ffmpeg, slide, still

p = argparse.ArgumentParser()
p.add_argument("out")
p.add_argument("--reference", required=True)
p.add_argument("--after", required=True)
p.add_argument("--return-note", required=True, help="how the return error was measured, and its value")
p.add_argument("--control", help="line for the unchanged control run")
p.add_argument("--model", help="VLM model named on the end slide")
p.add_argument("--patrol1", required=True)
p.add_argument("--change", help="clip of the scene being changed; a slide is used without it")
p.add_argument("--patrol2", required=True)
p.add_argument("--intro")
p.add_argument("--inset", help="camera.mp4 for patrol 2, shown in the corner")
p.add_argument("--inset-offset", type=float, default=0.0, help="seconds to skip at the start of the inset")
p.add_argument("--speed", type=float, default=2.0)
p.add_argument("--test", action="store_true", help="allow simulated runs to test this script; the output is marked TEST")
args = p.parse_args()

after = Path(args.after)
run = json.loads((after / "run.json").read_text())
if run.get("backend") != "go2" and not args.test:
    raise SystemExit("This run is not from the Go2. Use make_sim_demo.py for simulated runs.")
if run["status"] != "complete":
    print("WARNING: run status is", run["status"])
stations = run["stations"]
missing = [s for s, st in stations.items() if "changed" not in st.get("compare", {})]
if missing:
    raise SystemExit(f"No VLM result for {missing}. Run scripts/revlm.py first.")
for sid in stations:
    if not (after / "cards" / f"{sid}.png").exists():
        raise SystemExit("Cards not found. Run scripts/make_cards.py first.")
if not (after / "survey.png").exists():
    raise SystemExit("Survey not found. Run scripts/make_survey.py first.")

right = sum(st["compare"]["changed"] == (run["truth"][sid] != "none") for sid, st in stations.items())
speed = f"Video {args.speed:g}x." if args.speed != 1 else "Real time."
mark = "TEST BUILD, NOT A RESULT. " if args.test else ""


def clip(source, label, out, inset=None):
    cap = out.with_suffix(".png")
    caption(cap, mark + label)
    inputs, graph = ["-i", str(source), "-i", str(cap)], f"[0:v]setpts=PTS/{args.speed},{FIT}[v];[v][1:v]overlay=0:{SIZE[1] - 56}[o]"
    if inset:
        inputs += ["-ss", str(args.inset_offset), "-i", str(inset)]
        graph += f";[2:v]setpts=PTS/{args.speed},scale=426:-2[c];[o][c]overlay=W-w-10:10:shortest=0[o2]"
        last = "[o2]"
    else:
        last = "[o]"
    ffmpeg(*inputs, "-filter_complex", graph, "-map", last, "-shortest", "-an", str(out))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    parts = []

    def add_still(name, seconds):
        out = tmp / f"{name}.mp4"
        still(tmp / f"{name}.png", seconds, out)
        parts.append(out)

    slide(tmp / "title.png", "Second Look", [mark + "A Unitree Go2 inspects a site twice", "and reports what changed.", "", speed])
    add_still("title", 4)
    if args.intro:
        parts.append(tmp / "intro.mp4")
        clip(args.intro, "Before a crew arrives, the site must be checked again.", tmp / "intro.mp4")
    parts.append(tmp / "p1.mp4")
    clip(args.patrol1, f"Patrol 1: saving a reference view. {speed}", tmp / "p1.mp4")
    if args.change:
        parts.append(tmp / "change.mp4")
        clip(args.change, "We change the site by hand. Scout is not told what changed.", tmp / "change.mp4")
    else:
        slide(tmp / "change.png", "The site is changed by hand", [mark + "The robot is not told what changed."])
        add_still("change", 4)
    parts.append(tmp / "p2.mp4")
    clip(args.patrol2, f"Patrol 2: the same route. {speed}", tmp / "p2.mp4", args.inset)
    for sid in stations:
        out = tmp / f"card_{sid}.mp4"
        still(after / "cards" / f"{sid}.png", 6, out)
        parts.append(out)
    still(after / "survey.png", 6, tmp / "survey.mp4")
    parts.append(tmp / "survey.mp4")
    slide(tmp / "end.png", "Result of this run", [
        mark + f"Before/after: {right} of {len(stations)} stations correct, on this one run.",
        *([args.control] if args.control else []),
        args.return_note, *([f"Model: {args.model}"] if args.model else []), "",
        "The VLM reads images only. It cannot command the robot.",
        "Intended use: repeat site inspection. This is a lab mock-up."])
    add_still("end", 7)
    concat(parts, tmp / "list.txt", args.out)
print("saved", args.out)
