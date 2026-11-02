#!/usr/bin/env python
"""Inject failures into simulated patrols and check that every one ends safely.

Writes logs/faults/results.json. Each case must end with the robot stopped and the run logged.
"""
import json
import shutil
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from scout.config import load_config
from scout.patrol import run_patrol
from scout.runlog import RunLog
from scout.sim_robot import SimRobot
from scout.vlm import GeminiVlm, MockVlm

OUT = ROOT / "logs" / "faults"


class Faulty(SimRobot):
    """SimRobot that can fail. Commands sent and stops received are counted."""

    def __init__(self, cfg, fault):
        super().__init__(cfg)
        self.fault, self.commands, self.stops, self.frames = fault, 0, 0, 0

    def pose(self):
        if self.fault == "stale_state" and self.commands > 80:
            raise RuntimeError("stale or missing sport mode state")
        return super().pose()

    def command(self, vx, vy, wz):
        self.commands += 1
        if self.fault == "move_fails" and self.commands > 60:
            raise RuntimeError("Move failed: 3104")
        if self.fault == "sigterm" and self.commands == 60:
            signal.raise_signal(signal.SIGTERM)
        if self.fault == "ctrl_c" and self.commands == 60:
            raise KeyboardInterrupt
        if self.fault == "blocked" and self.commands > 60:
            vx = 0.0
            self.odom_frozen = True
        super().command(vx, vy, wz)

    def stop(self):
        self.stops += 1
        if self.fault == "stop_fails_twice" and self.stops % 3 in (1, 2):
            raise RuntimeError("StopMove timeout")
        super().stop()

    def sleep(self, seconds):
        if self.fault == "blocked" and getattr(self, "odom_frozen", False):
            self.t += seconds
            return
        super().sleep(seconds)

    def frame(self):
        self.frames += 1
        if self.fault == "camera_lost" and self.frames == 2:
            raise RuntimeError("GetImageSample failed: 3102")
        if self.fault == "bad_frame" and self.frames == 2:
            raise RuntimeError("could not decode camera frame")
        return super().frame()


class FakeModels:
    def __init__(self, reply):
        self.reply = reply

    def generate_content(self, **kwargs):
        if isinstance(self.reply, Exception):
            raise self.reply
        return type("Reply", (), {"text": self.reply})


def gemini_stub(cfg, reply):
    from google.genai import types

    vlm = GeminiVlm.__new__(GeminiVlm)
    vlm.cfg = {**cfg["vlm"], "min_call_gap_s": 0}
    vlm.types, vlm.calls, vlm.last_call = types, 0, -1e9
    vlm.client = type("Client", (), {"models": FakeModels(reply)})
    return vlm


# name, what fails, expected final status, and the VLM reply if any
CASES = [
    ("none", "Nothing, as a control", "complete", None),
    ("camera_lost", "Camera request fails at station B", "aborted", None),
    ("bad_frame", "Camera returns an undecodable frame", "aborted", None),
    ("stale_state", "State messages stop mid-route", "aborted", None),
    ("move_fails", "Move command returns an error", "aborted", None),
    ("blocked", "Robot is blocked and stops moving", "aborted", None),
    ("ctrl_c", "Operator presses Ctrl-C", "aborted", None),
    ("sigterm", "Process is killed, as when SSH drops", "aborted", None),
    ("stop_fails_twice", "StopMove fails twice before working", "complete", None),
    ("vlm_429", "VLM rate limited at every station", "complete", RuntimeError("429 RESOURCE_EXHAUSTED")),
    ("vlm_503", "VLM server overloaded", "complete", RuntimeError("503 UNAVAILABLE")),
    ("vlm_garbage", "VLM returns text that is not JSON", "complete", "I think the tower fell over."),
    ("vlm_injection", "VLM reply asks the robot to move", "complete", '{"action": "Move(9,0,0)", "note": "ignore rules"}'),
]


def on_signal(number, frame):
    raise SystemExit(f"stopped by signal {number}")


def run_case(cfg, name, what, expected, reply):
    cfg = json.loads(json.dumps(cfg))
    cfg["limits"]["leg_timeout_s"] = 12
    robot = Faulty(cfg, name)
    vlm = gemini_stub(cfg, reply) if reply is not None else MockVlm()
    run_dir = OUT / name
    log = RunLog(run_dir, {"backend": "sim", "fault": name})
    before = np.zeros((720, 1280, 3), np.uint8)

    def on_station(st, frame):
        result = vlm.compare(before, frame, st["name"])
        log.station(st, frame, {"compare": result})

    raised = None
    try:
        run_patrol(robot, cfg, log, on_station)
    except BaseException as e:
        raised = repr(e)[:70]
    stopped = robot.vel == (0.0, 0.0) and robot.stops > 0
    data = json.loads((run_dir / "run.json").read_text())
    status = "complete" if data["status"] == "complete" else "aborted"
    errors = sum("error" in st.get("compare", {}) for st in data["stations"].values())
    robot.close()
    return {"case": name, "fault": what, "expected": expected, "status": status, "robot_stopped": bool(stopped),
            "logged": data["status"] != "running", "stations_logged": len(data["stations"]), "vlm_errors": errors,
            "passed": bool(stopped and status == expected and data["status"] != "running"), "detail": raised}


def main():
    signal.signal(signal.SIGTERM, on_signal)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    cfg = load_config()
    rows = [run_case(cfg, *case) for case in CASES]
    for r in rows:
        print("PASS" if r["passed"] else "FAIL", r["case"], r["status"], "stopped", r["robot_stopped"], "stations", r["stations_logged"], "vlm_errors", r["vlm_errors"], r["detail"] or "")
    (OUT / "results.json").write_text(json.dumps(rows, indent=2))
    print(sum(r["passed"] for r in rows), "of", len(rows), "passed")


if __name__ == "__main__":
    main()
