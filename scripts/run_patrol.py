#!/usr/bin/env python
"""Run one patrol in sim or on the Go2.

Sim, reference patrol:   run_patrol.py --backend sim --phase before --run sim_ref
Sim, after a change:     run_patrol.py --backend sim --phase after --run sim_1 --reference logs/sim_ref --change tower_fallen
Go2, after a change:     run_patrol.py --backend go2 --phase after --run go2_1 --reference logs/go2_ref --truth B=added --remote-in-hand
"""
import argparse
import datetime
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from scout.config import load_config
from scout.patrol import run_patrol
from scout.runlog import RunLog
from scout.vlm import GeminiVlm, MockVlm, OllamaVlm


def parse_truth(items, stations):
    truth = {s["id"]: "none" for s in stations}
    for item in items:
        station, kind = item.split("=")
        if station not in truth:
            raise SystemExit(f"unknown station {station}")
        truth[station] = kind
    return truth


def on_signal(number, frame):
    """Turn a kill or a lost SSH session into an exception, so the stop path runs."""
    raise SystemExit(f"stopped by signal {number}")


def main():
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["sim", "go2"], required=True)
    p.add_argument("--phase", choices=["before", "after"], required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--reference", help="run folder of the before patrol")
    p.add_argument("--vlm", choices=["gemini", "ollama", "mock", "none"], default="gemini", help="none: only save frames, then use revlm.py")
    p.add_argument("--change", nargs="*", default=[], help="sim only: scene changes")
    p.add_argument("--truth", nargs="*", default=[], help="go2: true labels written before the run, e.g. B=added")
    p.add_argument("--single", action="store_true", help="also run the single-frame baseline, one extra call per station")
    p.add_argument("--realign", action="store_true", help="after phase: correct each stop against the reference frame")
    p.add_argument("--seed", type=int)
    p.add_argument("--config", help="mission file, for example a scan scene from scan_to_mujoco.py")
    p.add_argument("--video", action="store_true", help="sim only: write patrol.mp4")
    p.add_argument("--record", action="store_true", help="go2 only: save the camera feed for the video")
    p.add_argument("--remote-in-hand", action="store_true", help="required on the Go2")
    args = p.parse_args()

    cfg = load_config(args.config)
    run_dir = ROOT / "logs" / args.run
    if run_dir.exists():
        raise SystemExit(f"{run_dir} already exists")
    if args.backend == "go2" and not args.remote_in_hand:
        raise SystemExit("Go2 runs need --remote-in-hand: area clear, remote held, cable handled.")
    if args.phase == "after" and not args.reference:
        raise SystemExit("--phase after needs --reference")

    vlm = None
    if args.phase == "after" and args.vlm != "none":
        vlm = {"gemini": GeminiVlm, "ollama": OllamaVlm}[args.vlm](cfg["vlm"]) if args.vlm != "mock" else MockVlm()

    if args.backend == "sim":
        from scout.sim_robot import CHANGE_KIND, CHANGE_STATION, SimRobot

        truth = parse_truth([f"{CHANGE_STATION[c]}={CHANGE_KIND[c]}" for c in args.change], cfg["stations"])
        run_dir.mkdir(parents=True)
        robot = SimRobot(cfg, args.change, args.seed, run_dir / "patrol.mp4" if args.video else None)
    else:
        from scout.robot import Go2Robot

        truth = parse_truth(args.truth, cfg["stations"])
        robot = Go2Robot(cfg)

    log = RunLog(run_dir, {
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "backend": args.backend, "phase": args.phase, "reference": args.reference,
        "vlm": vlm.backend if vlm else None, "model": getattr(vlm, "model", None) or (cfg["vlm"]["model"] if args.vlm == "gemini" else None),
        "truth": truth, "changes": args.change,
    })

    def on_station(st, frame):
        result = {}
        if vlm:
            before = np.array(Image.open(Path(args.reference) / "frames" / f"{st['id']}.jpg").convert("RGB"))
            result = {"compare": vlm.compare(before, frame, st["name"])}
            if args.single:
                result["single"] = vlm.single(frame, st["name"])
            print(st["id"], result["compare"].get("summary", result["compare"].get("error")))
        log.station(st, frame, result)

    on_arrive = None
    if args.realign:
        from scout.align import realign

        def on_arrive(st, guard):
            before = np.array(Image.open(Path(args.reference) / "frames" / f"{st['id']}.jpg").convert("RGB"))
            log.data.setdefault("realign", {})[st["id"]] = realign(robot, cfg, guard, log, before)

    recorder = None
    if args.record and args.backend == "go2":
        from scout.recorder import CameraRecorder

        recorder = CameraRecorder(robot.jpeg, run_dir / "camera")
        recorder.start()
    try:
        run_patrol(robot, cfg, log, on_station, on_arrive)
        if args.backend == "sim":
            log.data["true_final_pose"] = list(robot.true_pose())
            log.save()
    finally:
        if recorder:
            recorder.stop()
        robot.close()
    if vlm:
        print("VLM calls:", vlm.calls)
    print("saved", run_dir)


if __name__ == "__main__":
    main()
