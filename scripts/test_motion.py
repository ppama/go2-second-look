#!/usr/bin/env python
"""First motion test: stand, walk slowly for a short time, stop, print odometry."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scout.config import load_config
from scout.robot import Go2Robot

p = argparse.ArgumentParser()
p.add_argument("--speed", type=float, default=0.15)
p.add_argument("--seconds", type=float, default=1.0)
p.add_argument("--stand-only", action="store_true")
p.add_argument("--remote-in-hand", action="store_true")
args = p.parse_args()

if not args.remote_in_hand:
    raise SystemExit("Needs --remote-in-hand: area clear, remote held, cable handled.")
if not 0 < args.speed <= 0.2 or not 0 < args.seconds <= 2.0:
    raise SystemExit("Test limits: speed up to 0.2 m/s, time up to 2 s.")

robot = Go2Robot(load_config())
try:
    robot.start()
    print("standing, pose:", robot.pose())
    if not args.stand_only:
        end = robot.now() + args.seconds
        while robot.now() < end:
            robot.command(args.speed, 0.0, 0.0)
            robot.sleep(0.1)
        robot.stop()
        robot.sleep(1.0)
        print("after move, pose:", robot.pose(), "expected about", round(args.speed * args.seconds, 3), "m forward")
finally:
    robot.stop()
