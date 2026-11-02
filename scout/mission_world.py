"""Connects mission programs to the patrol controller, with vision supplied separately."""
import math

from scout.mission_lang import Result
from scout.patrol import Guard, face, go_to
from scout.robot import wrap

LOOK_TURN = 0.3


class NullLog:
    def odom(self, *values):
        pass


class TruthVision:
    """Test stand-in: answers from the known scene. It checks program logic, not perception."""

    def __init__(self, truth):
        self.truth = truth

    def inspect(self, station, frame):
        changed = self.truth.get(station, "none") != "none"
        return Result(changed, changed, "stand-in result from the known scene")


class World:
    def __init__(self, robot, cfg, vision):
        self.robot, self.cfg, self.vision = robot, cfg, vision
        self.stations = {s["id"]: s for s in cfg["stations"]}
        self.guard = Guard(robot, cfg["limits"])
        self.log = NullLog()
        self.station = None

    def go_to(self, station):
        st = self.stations[station]
        go_to(self.robot, self.cfg, self.guard, self.log, st["x"], st["y"])
        face(self.robot, self.cfg, self.guard, self.log, st["yaw"])
        self.robot.sleep(self.cfg["control"]["settle_s"])
        self.station = station

    def inspect(self):
        if self.station is None:
            return Result(False, False, "no station visited")
        return self.vision.inspect(self.station, self.robot.frame())

    def look_again(self):
        """A second view from the same spot, at a small fixed turn."""
        if self.station is None:
            return Result(False, False, "no station visited")
        yaw = self.stations[self.station]["yaw"]
        face(self.robot, self.cfg, self.guard, self.log, wrap(yaw + LOOK_TURN))
        self.robot.sleep(self.cfg["control"]["settle_s"])
        result = self.vision.inspect(self.station, self.robot.frame())
        face(self.robot, self.cfg, self.guard, self.log, yaw)
        return result

    def return_home(self):
        go_to(self.robot, self.cfg, self.guard, self.log, 0.0, 0.0)
        face(self.robot, self.cfg, self.guard, self.log, 0.0)


def home_error(robot):
    x, y, _ = robot.pose()
    return math.hypot(x, y)
