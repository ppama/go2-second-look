"""Robot backends. The patrol only sees this interface, so the same code runs in sim and on the Go2."""
import math
import threading
import time

import numpy as np


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def clamp_velocity(limits, vx, vy, wz):
    return (
        float(np.clip(vx, -limits["max_vx"], limits["max_vx"])),
        float(np.clip(vy, -limits["max_vy"], limits["max_vy"])),
        float(np.clip(wz, -limits["max_wz"], limits["max_wz"])),
    )


class Go2Robot:
    """Real Go2 over DDS: SportClient for motion, VideoClient for the front camera."""

    def __init__(self, cfg):
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
        from unitree_sdk2py.go2.sport.sport_client import SportClient
        from unitree_sdk2py.go2.video.video_client import VideoClient
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

        self.limits = cfg["limits"]
        self.state_timeout = cfg["robot"]["state_timeout_s"]
        self._state = None
        self._stamp = 0.0
        self._lock = threading.Lock()
        self._video_lock = threading.Lock()
        self._origin = None

        ChannelFactoryInitialize(0, cfg["robot"]["interface"])
        self._sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
        self._sub.Init(self._on_state, 10)
        self.sport = SportClient()
        self.sport.SetTimeout(10.0)
        self.sport.Init()
        self.video = VideoClient()
        self.video.SetTimeout(3.0)
        self.video.Init()

    def _on_state(self, msg):
        with self._lock:
            self._state, self._stamp = msg, time.monotonic()

    def _raw_pose(self):
        with self._lock:
            state, stamp = self._state, self._stamp
        if state is None or time.monotonic() - stamp > self.state_timeout:
            raise RuntimeError("stale or missing sport mode state")
        return float(state.position[0]), float(state.position[1]), float(state.imu_state.rpy[2])

    def start(self):
        """Stand, then define the mission frame from the current pose."""
        code = self.sport.StandUp()
        if code != 0:
            raise RuntimeError(f"StandUp failed: {code}")
        self.sleep(2.0)
        code = self.sport.BalanceStand()
        if code != 0:
            raise RuntimeError(f"BalanceStand failed: {code}")
        self.sleep(1.0)
        self._origin = self._raw_pose()

    def pose(self):
        x, y, yaw = self._raw_pose()
        x0, y0, yaw0 = self._origin
        c, s = math.cos(-yaw0), math.sin(-yaw0)
        dx, dy = x - x0, y - y0
        return c * dx - s * dy, s * dx + c * dy, wrap(yaw - yaw0)

    def command(self, vx, vy, wz):
        vx, vy, wz = clamp_velocity(self.limits, vx, vy, wz)
        code = self.sport.Move(vx, vy, wz)
        if code not in (0, None):
            raise RuntimeError(f"Move failed: {code}")

    def stop(self):
        self.sport.StopMove()

    def jpeg(self):
        with self._video_lock:
            code, data = self.video.GetImageSample()
        if code != 0:
            raise RuntimeError(f"GetImageSample failed: {code}")
        return bytes(data)

    def frame(self):
        import cv2

        bgr = cv2.imdecode(np.frombuffer(self.jpeg(), np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError("could not decode camera frame")
        return bgr[:, :, ::-1]

    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)

    def close(self):
        pass
