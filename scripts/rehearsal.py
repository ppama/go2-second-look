#!/usr/bin/env python
"""Dress rehearsal in simulation, to plan the hardware run.

Runs one reference patrol and a matrix of after-patrols at several drift levels, then writes
logs/rehearsal/results.json. Uses pixel difference and the local detector, so no API quota.
Drift values are assumptions: use this to find failure modes, not to predict robot performance.
"""
import copy
import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from scout.align import realign
from scout.config import load_config
from scout.detector import Detector
from scout.patrol import run_patrol
from scout.runlog import RunLog
from scout.sim_robot import CHANGE_KIND, CHANGE_STATION, SimRobot
from scout.vlm import MockVlm

OUT = ROOT / "logs" / "rehearsal"
LEVELS = {"base": 1.0, "x2": 2.0, "x4": 4.0, "x8": 8.0}
SCENES = [[], ["tower_fallen"], ["block_removed"], ["rock_added"], ["block_moved"], ["tower_fallen", "block_removed"]]


def drifted(cfg, factor):
    cfg = copy.deepcopy(cfg)
    for key in ("slip", "yaw_gain_error", "yaw_rate_bias"):
        cfg["sim"][key] *= factor
    return cfg


def patrol(cfg, name, changes, seed, reference=None, models=(), align=False):
    run_dir = OUT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    truth = {s["id"]: "none" for s in cfg["stations"]}
    for change in changes:
        truth[CHANGE_STATION[change]] = CHANGE_KIND[change]
    robot = SimRobot(cfg, changes, seed)
    log = RunLog(run_dir, {"backend": "sim", "phase": "after" if reference else "before", "truth": truth,
                           "changes": list(changes), "reference": None, "vlm": None, "model": None})
    frames, stops = {}, {}

    def on_station(st, frame):
        stops[st["id"]] = robot.true_pose()
        frames[st["id"]] = frame
        result = {m.backend: m.compare(reference["frames"][st["id"]], frame, st["name"]) for m in models} if reference else {}
        log.station(st, frame, result)

    def on_arrive(st, guard):
        matched[st["id"]] = realign(robot, cfg, guard, log, reference["frames"][st["id"]])

    matched = {}
    run_patrol(robot, cfg, log, on_station, on_arrive if align else None)
    true_end, odom_end = robot.true_pose(), robot.pose()
    seconds = robot.now()
    robot.close()
    return {"frames": frames, "stops": stops, "truth": truth, "seconds": seconds, "stations": log.data["stations"],
            "true_return_m": math.hypot(*true_end[:2]), "odom_return_m": math.hypot(*odom_end[:2]), "matched": matched}


def main():
    global OUT
    p = argparse.ArgumentParser()
    p.add_argument("--realign", action="store_true")
    args = p.parse_args()
    if args.realign:
        OUT = ROOT / "logs" / "rehearsal_aligned"
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    started = time.time()
    reference = patrol(cfg, "ref", [], 0)
    models = [MockVlm(), Detector(ROOT / "output" / "detector" / "change_net.pt")]
    rows = []
    for level, factor in LEVELS.items():
        level_cfg = drifted(cfg, factor)
        for s, scene in enumerate(SCENES):
            for seed in (101, 202):
                name = f"{level}_{s}_{seed}"
                run = patrol(level_cfg, name, scene, seed + s, reference, models, args.realign)
                for sid, st in run["stations"].items():
                    stop, ref = run["stops"][sid], reference["stops"][sid]
                    rows.append({
                        "level": level, "run": name, "station": sid, "truth": run["truth"][sid],
                        "stop_shift_cm": 100 * math.hypot(stop[0] - ref[0], stop[1] - ref[1]),
                        "yaw_shift_deg": abs(math.degrees((stop[2] - ref[2] + math.pi) % (2 * math.pi) - math.pi)),
                        "pixel": st["mock"]["changed"], "detector": st["detector"]["changed"],
                        "matched": bool(run["matched"].get(sid) and run["matched"][sid][0].get("matched")) if args.realign else None,
                        "true_return_cm": 100 * run["true_return_m"], "odom_return_cm": 100 * run["odom_return_m"],
                        "patrol_s": run["seconds"],
                    })
    (OUT / "results.json").write_text(json.dumps(rows))

    def stats(items):
        pos = [r for r in items if r["truth"] != "none"]
        neg = [r for r in items if r["truth"] == "none"]
        out = {"stations": len(items), "stop_shift_cm_p50": np.percentile([r["stop_shift_cm"] for r in items], 50),
               "stop_shift_cm_max": max(r["stop_shift_cm"] for r in items), "yaw_shift_deg_p50": np.percentile([r["yaw_shift_deg"] for r in items], 50), "yaw_shift_deg_max": max(r["yaw_shift_deg"] for r in items),
               "true_return_cm_max": max(r["true_return_cm"] for r in items), "odom_return_cm_max": max(r["odom_return_cm"] for r in items)}
        for m in ("pixel", "detector"):
            out[f"{m}_caught"] = f"{sum(r[m] for r in pos)}/{len(pos)}"
            out[f"{m}_false_alarms"] = f"{sum(r[m] for r in neg)}/{len(neg)}"
        out["no_match"] = sum(r["matched"] is False for r in items)
        return {k: round(float(v), 1) if not isinstance(v, (str, int)) else v for k, v in out.items()}

    summary = {"patrol_seconds": round(float(np.mean([r["patrol_s"] for r in rows])), 1),
               "levels": {level: stats([r for r in rows if r["level"] == level]) for level in LEVELS},
               "by_change": {}, "runtime_s": round(time.time() - started)}
    kinds = sorted({r["truth"] for r in rows if r["truth"] != "none"})
    for kind in kinds:
        items = [r for r in rows if r["truth"] == kind and r["level"] in ("base", "x2")]
        summary["by_change"][kind] = {m: f"{sum(r[m] for r in items)}/{len(items)}" for m in ("pixel", "detector")}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
