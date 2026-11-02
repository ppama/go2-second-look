from pathlib import Path
import math
import json

import numpy as np
import pytest

from scout.config import load_config
from scout.patrol import Guard, PatrolAbort, go_to, run_patrol
from scout.robot import Go2Robot, clamp_velocity, wrap
from scout.runlog import RunLog
from scout.sim_robot import SimRobot
from scout.vlm import GeminiVlm, MockVlm, parse_reply


@pytest.fixture
def cfg():
    return load_config()


def test_clamp(cfg):
    assert clamp_velocity(cfg["limits"], 9, 9, -9) == (0.30, 0.0, -0.60)


def test_wrap():
    assert abs(wrap(3 * math.pi) - math.pi) < 1e-9 or abs(wrap(3 * math.pi) + math.pi) < 1e-9


def test_parse_fenced_json():
    r = parse_reply('text ```json\n{"changed": true, "hazard": false, "changes": [{"type":"added","label":"rock","box_2d":[1,2,3,4]}], "summary":"s"}\n```')
    assert r["changed"] and r["changes"][0]["box_2d"] == [1, 2, 3, 4]


def test_parse_drops_bad_box():
    r = parse_reply('{"changed": true, "hazard": true, "changes": [{"label":"x","box_2d":[1,2,3000,4]}]}')
    assert r["changes"][0]["box_2d"] is None


@pytest.mark.parametrize("text", ["", "no json", '{"changed": "yes", "hazard": false}'])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parse_reply(text)


def test_route_stays_clear_of_scenes(cfg):
    """No patrol waypoint leads into the prop rows at y < -1.2 or y > 1.9."""
    for st in cfg["stations"]:
        assert -1.2 < st["y"] < 1.9


def test_patrol_returns_and_logs(cfg, tmp_path):
    robot = SimRobot(cfg)
    log = RunLog(tmp_path / "r", {"truth": {}})
    seen = []
    run_patrol(robot, cfg, log, lambda st, f: (seen.append(st["id"]), log.station(st, f, {})))
    assert seen == ["A", "B", "C"]
    data = json.loads((tmp_path / "r" / "run.json").read_text())
    assert data["status"] == "complete"
    assert math.hypot(*data["final_odom_pose"][:2]) < cfg["control"]["pos_tol"]
    assert robot.vel == (0.0, 0.0)
    robot.close()


def test_stop_called_when_station_fails(cfg, tmp_path):
    robot = SimRobot(cfg)
    log = RunLog(tmp_path / "r", {})

    def boom(st, frame):
        robot.command(0.3, 0, 0)
        raise RuntimeError("camera lost")

    with pytest.raises(RuntimeError):
        run_patrol(robot, cfg, log, boom)
    assert robot.vel == (0.0, 0.0)
    assert "aborted" in json.loads((tmp_path / "r" / "run.json").read_text())["status"]
    robot.close()


def test_guard_time_limit(cfg, tmp_path):
    cfg["limits"]["mission_timeout_s"] = 1
    robot = SimRobot(cfg)
    guard = Guard(robot, cfg["limits"])
    log = RunLog(tmp_path / "r", {})
    with pytest.raises(PatrolAbort):
        go_to(robot, cfg, guard, log, 5.0, 0.0)
    robot.close()


def test_change_is_visible_in_camera(cfg):
    """Same pose, changed scene: station C's frame must differ."""
    frames = []
    for change in ([], ["block_removed"]):
        robot = SimRobot(cfg, change)
        robot.true = np.array([2.1, 0.0, -math.pi / 2])
        robot._write_pose()
        frames.append(robot.frame())
        robot.close()
    assert MockVlm().compare(frames[0], frames[1], "c")["changed"]
    assert not MockVlm().compare(frames[0], frames[0], "c")["changed"]


class FakeModels:
    def __init__(self, replies):
        self.replies, self.count = replies, 0

    def generate_content(self, **kwargs):
        self.count += 1
        reply = self.replies[self.count - 1]
        if isinstance(reply, Exception):
            raise reply
        return type("Reply", (), {"text": reply})


def fake_gemini(cfg, replies, retries=0):
    from google.genai import types

    vlm = GeminiVlm.__new__(GeminiVlm)
    vlm.cfg = {**cfg["vlm"], "retries": retries, "min_call_gap_s": 0}
    vlm.types, vlm.calls, vlm.last_call = types, 0, -1e9
    vlm.client = type("Client", (), {"models": FakeModels(replies)})
    return vlm


def test_rate_limit_is_not_retried(cfg):
    vlm = fake_gemini(cfg, [RuntimeError("429 RESOURCE_EXHAUSTED")] * 3, retries=2)
    result = vlm.single(np.zeros((90, 160, 3), "u1"), "c")
    assert "error" in result and vlm.calls == 1


def test_bad_reply_stops_at_retry_limit(cfg):
    vlm = fake_gemini(cfg, ["no json", "no json"], retries=1)
    assert "error" in vlm.single(np.zeros((90, 160, 3), "u1"), "c")
    assert vlm.calls == 2


def test_compare_calls_once(cfg):
    good = '{"changed": false, "hazard": false, "changes": [], "summary": "ok"}'
    vlm = fake_gemini(cfg, [good])
    frame = np.zeros((90, 160, 3), "u1")
    assert vlm.compare(frame, frame, "c")["changed"] is False
    assert vlm.calls == 1


class FakeState:
    def __init__(self, x, y, yaw):
        self.position = [x, y, 0.3]
        self.imu_state = type("Imu", (), {"rpy": [0, 0, yaw]})


class FakeSport:
    def __init__(self, codes=None):
        self.moves, self.stops, self.codes = [], 0, codes or {}

    def StandUp(self):
        return self.codes.get("stand", 0)

    def BalanceStand(self):
        return 0

    def Move(self, vx, vy, wz):
        self.moves.append((vx, vy, wz))
        return 0

    def StopMove(self):
        self.stops += 1
        return 0


def fake_go2(cfg, sport=None):
    import threading
    import time

    robot = Go2Robot.__new__(Go2Robot)
    robot.limits, robot.state_timeout = cfg["limits"], 0.5
    robot._lock, robot._video_lock = threading.Lock(), threading.Lock()
    robot._state, robot._stamp, robot._origin = None, 0.0, None
    robot.sport = sport or FakeSport()
    robot.sleep = lambda s: None
    robot._on_state(FakeState(5.0, -2.0, math.pi / 2))
    return robot, time


def test_go2_mission_frame_is_relative_to_start(cfg):
    robot, _ = fake_go2(cfg)
    robot.start()
    assert robot.pose() == pytest.approx((0, 0, 0), abs=1e-9)
    # Started facing +y in odometry, so odometry +y is mission forward.
    robot._on_state(FakeState(5.0, -1.0, math.pi / 2))
    assert robot.pose() == pytest.approx((1, 0, 0), abs=1e-6)


def test_go2_commands_are_clamped(cfg):
    robot, _ = fake_go2(cfg)
    robot.command(5, 5, -5)
    assert robot.sport.moves == [(0.30, 0.0, -0.60)]


def test_go2_stale_state_raises(cfg):
    robot, time = fake_go2(cfg)
    robot.start()
    robot._stamp = time.monotonic() - 2
    with pytest.raises(RuntimeError):
        robot.pose()


def test_go2_stand_failure_raises(cfg):
    robot, _ = fake_go2(cfg, FakeSport({"stand": 3104}))
    with pytest.raises(RuntimeError):
        robot.start()


def test_go2_stale_state_during_patrol_stops_robot(cfg, tmp_path):
    robot, time = fake_go2(cfg)
    original = robot.command

    def lose_state(vx, vy, wz):
        original(vx, vy, wz)
        robot._stamp = time.monotonic() - 2

    robot.command = lose_state
    log = RunLog(tmp_path / "r", {})
    with pytest.raises(RuntimeError):
        run_patrol(robot, cfg, log, lambda st, f: None)
    assert robot.sport.stops >= 1


def test_recorder_survives_grab_errors(tmp_path):
    import time

    from scout.recorder import CameraRecorder

    calls = {"n": 0}

    def grab():
        calls["n"] += 1
        if calls["n"] % 2:
            raise RuntimeError("camera busy")
        return b"jpeg"

    rec = CameraRecorder(grab, tmp_path / "cam", rate_hz=200)
    rec.start()
    time.sleep(0.1)
    rec.stop()
    assert rec.count >= 1 and rec.error


def test_failed_stop_is_retried():
    from scout.patrol import stop_robot

    class Flaky:
        calls = 0

        def stop(self):
            Flaky.calls += 1
            if Flaky.calls < 3:
                raise RuntimeError("timeout")

    stop_robot(Flaky())
    assert Flaky.calls == 3


def test_stop_failure_is_reported():
    from scout.patrol import stop_robot

    class Dead:
        def stop(self):
            raise RuntimeError("timeout")

    with pytest.raises(RuntimeError):
        stop_robot(Dead())


def test_align_measures_a_known_turn(cfg):
    from scout.align import estimate

    robot = SimRobot(cfg)
    robot.true = np.array([1.35, 1.3, math.pi / 2])
    robot._write_pose()
    reference = robot.frame()
    robot.true[2] += 0.15
    robot._write_pose()
    result = estimate(reference, robot.frame(), cfg["camera"]["fx"])
    robot.close()
    assert result and abs(result["yaw"] - 0.15) < 0.05


def test_align_gives_up_on_a_blank_view():
    from scout.align import estimate

    blank = np.full((720, 1280, 3), 120, np.uint8)
    assert estimate(blank, blank, 565) is None


def test_realign_refuses_a_large_correction(cfg, monkeypatch):
    import scout.align as align

    robot = SimRobot(cfg)
    robot.command = lambda *a: pytest.fail("no motion expected")
    monkeypatch.setattr(align, "estimate", lambda *a: {"yaw": 1.2, "scale": 1.0, "inliers": 200})
    out = align.realign(robot, cfg, Guard(robot, cfg["limits"]), None, robot.frame())
    robot.close()
    assert out[0]["rejected"]


def test_ollama_side_by_side_keeps_both_views():
    from scout.vlm import OllamaVlm

    vlm = OllamaVlm({"image_width": 800, "temperature": 0.1})
    before, after = np.zeros((40, 60, 3), np.uint8), np.full((40, 60, 3), 200, np.uint8)
    sheet = vlm._side_by_side(before, after)
    assert sheet.shape == (40, 128, 3)
    assert sheet[0, 0, 0] == 0 and sheet[0, 62, 0] == 255 and sheet[0, 127, 0] == 200


def test_overlap_declines_unrelated_views_and_greys_unseen_area():
    from PIL import Image

    from scout.align import overlap

    frame = np.array(Image.open("logs/rehearsal/ref/frames/B.jpg").convert("RGB")) if Path("logs/rehearsal/ref/frames/B.jpg").exists() else None
    if frame is None:
        return
    shifted = np.roll(frame, 60, axis=1)
    left, right = overlap(frame, shifted)
    assert (left[:, :20] == 128).all() or (left[:, -20:] == 128).all()
    assert overlap(frame, np.zeros_like(frame)) is None


def load_teleop():
    import importlib.util

    spec = importlib.util.spec_from_file_location("teleop", "scripts/teleop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDrive:
    def __init__(self, fail=False):
        self.commands, self.stops, self.fail = [], 0, fail

    def command(self, vx, vy, wz):
        if self.fail:
            raise RuntimeError("Move failed")
        self.commands.append((vx, vy, wz))

    def stop(self):
        self.stops += 1


def make_teleop(robot):
    return load_teleop().Teleop(robot, {"max_vx": 0.3, "max_vy": 0.0, "max_wz": 0.6})


def test_teleop_moves_only_while_held_and_clamps():
    robot = FakeDrive()
    t = make_teleop(robot)
    t.tick({"w", "a"}, 0, 0)
    assert robot.commands == [(0.2, 0.0, 0.5)]
    t.tick(set(), 0, 0)
    t.tick(set(), 0, 0)
    assert len(robot.commands) == 1 and robot.stops == 1


def test_teleop_stops_on_stale_input_camera_latch_and_failure():
    for keys_age, camera_age in ((1.0, 0), (0, 2.0)):
        robot = FakeDrive()
        t = make_teleop(robot)
        t.tick({"w"}, 0, 0)
        t.tick({"w"}, keys_age, camera_age)
        assert robot.stops == 1 and len(robot.commands) == 1
    robot = FakeDrive()
    t = make_teleop(robot)
    t.tick({"w"}, 0, 0)
    t.latched = True
    t.tick({"w"}, 0, 0)
    assert robot.stops == 1 and len(robot.commands) == 1
    robot = FakeDrive(fail=True)
    t = make_teleop(robot)
    t.tick({"w"}, 0, 0)
    assert robot.stops == 1 and t.latched


def test_teleop_turns_in_place_sidesteps_and_stays_clamped():
    robot = FakeDrive()
    t = make_teleop(robot)
    t.tick({"a"}, 0, 0)
    t.tick({"d"}, 0, 0)
    t.tick({"q"}, 0, 0)
    t.set_gear("3")
    t.speed = 5.0
    t.tick({"w", "e"}, 0, 0)
    assert robot.commands == [(0.0, 0.0, 0.5), (0.0, 0.0, -0.5), (0.0, 0.15, 0.0), (0.3, -0.2, 0.0)]
