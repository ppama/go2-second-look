"""Waypoint patrol in the odometry frame. The VLM runs only while the robot is stopped."""
import math

from scout.robot import wrap


class PatrolAbort(RuntimeError):
    pass


class Guard:
    """Mission time and step limits, checked on every control tick."""

    def __init__(self, robot, limits):
        self.robot, self.limits = robot, limits
        self.start = robot.now()
        self.steps = 0

    def tick(self, leg_start):
        self.steps += 1
        now = self.robot.now()
        if self.steps > self.limits["max_steps"]:
            raise PatrolAbort("step limit")
        if now - self.start > self.limits["mission_timeout_s"]:
            raise PatrolAbort("mission timeout")
        if now - leg_start > self.limits["leg_timeout_s"]:
            raise PatrolAbort("leg timeout")


def go_to(robot, cfg, guard, log, x, y):
    ctl, dt = cfg["control"], cfg["limits"]["control_dt_s"]
    leg_start = robot.now()
    while True:
        guard.tick(leg_start)
        px, py, yaw = robot.pose()
        dist = math.hypot(x - px, y - py)
        if dist < ctl["pos_tol"]:
            break
        err = wrap(math.atan2(y - py, x - px) - yaw)
        vx = 0.0 if abs(err) > ctl["turn_first_rad"] else ctl["k_pos"] * dist
        wz = ctl["k_yaw"] * err
        robot.command(vx, 0.0, wz)
        log.odom(robot.now(), px, py, yaw, vx, wz)
        robot.sleep(dt)
    stop_robot(robot)


def face(robot, cfg, guard, log, target):
    ctl, dt = cfg["control"], cfg["limits"]["control_dt_s"]
    leg_start = robot.now()
    while True:
        guard.tick(leg_start)
        px, py, yaw = robot.pose()
        err = wrap(target - yaw)
        if abs(err) < ctl["yaw_tol"]:
            break
        wz = ctl["k_yaw"] * err
        robot.command(0.0, 0.0, wz)
        log.odom(robot.now(), px, py, yaw, 0.0, wz)
        robot.sleep(dt)
    stop_robot(robot)


def stop_robot(robot, tries=3):
    """A failed stop is retried, because it is the one command that must get through."""
    last = None
    for _ in range(tries):
        try:
            robot.stop()
            return
        except Exception as e:
            last = e
    raise RuntimeError(f"stop failed after {tries} tries") from last


def run_patrol(robot, cfg, log, on_station, on_arrive=None):
    """Visit every station, call on_station(station, frame), then return to start.

    on_arrive(station, guard) runs after each stop, before the frame is taken. The robot is always
    stopped on the way out, including on any error.
    """
    try:
        robot.start()
        guard = Guard(robot, cfg["limits"])
        for st in cfg["stations"]:
            go_to(robot, cfg, guard, log, st["x"], st["y"])
            face(robot, cfg, guard, log, st["yaw"])
            robot.sleep(cfg["control"]["settle_s"])
            if on_arrive:
                on_arrive(st, guard)
            pause_start = robot.now()
            pause_start = robot.now()
            on_station(st, robot.frame())
            guard.start += robot.now() - pause_start  # VLM time is not mission time
            guard.start += robot.now() - pause_start  # VLM time is not mission time
        go_to(robot, cfg, guard, log, 0.0, 0.0)
        face(robot, cfg, guard, log, 0.0)
        log.finish("complete", robot.pose())
    except BaseException as e:
        log.finish(f"aborted: {e!r}", None)
        raise
    finally:
        stop_robot(robot)
