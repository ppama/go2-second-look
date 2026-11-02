"""MuJoCo stand-in for Go2Robot. The body follows velocity commands with slip; legs are only animated.

Odometry does not see the slip, as on the real robot, so true and odometry poses drift apart.
"""
import math
import os
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco
import numpy as np

from scout.robot import clamp_velocity, wrap

SCENE = Path(__file__).resolve().parent.parent / "sim" / "scene.xml"

# Scene changes for the before/after task. Each maps to (body, position, yaw about x or None).
CHANGES = {
    "tower_fallen": ("tower_b", (1.55, 2.35, 0.03), -1.5708),
    "rock_added": ("rock_b", (1.1, 2.0, 0.0), None),
    "block_removed": ("block_c", (0, 0, -5), None),
    "block_moved": ("block_c", (2.75, -1.25, 0.08), None),
}
CHANGE_STATION = {"tower_fallen": "B", "rock_added": "B", "block_removed": "C", "block_moved": "C"}
CHANGE_KIND = {"tower_fallen": "fallen", "rock_added": "added", "block_removed": "removed", "block_moved": "moved"}


class SimRobot:
    def __init__(self, cfg, changes=(), seed=None, video_path=None):
        from sim.make_textures import build

        build()
        self.limits = cfg["limits"]
        self.rng = np.random.default_rng(cfg["sim"]["seed"] if seed is None else seed)
        # Each run gets its own slip and heading error, as each real walk does.
        self.sim = dict(cfg["sim"])
        for key in ("slip", "yaw_gain_error", "yaw_rate_bias"):
            self.sim[key] *= self.rng.uniform(0.5, 1.5)
        scene = SCENE.parent / cfg["sim"]["scene"] if cfg["sim"].get("scene") else SCENE
        self.origin = cfg["sim"].get("origin", [0.0, 0.0, 0.0])
        self.model = mujoco.MjModel.from_xml_path(str(scene))
        self.data = mujoco.MjData(self.model)
        self.home = self.model.key("home").qpos.copy()
        for name in changes:
            self._apply(name)
        self.true = np.zeros(3)
        self.odom = np.zeros(3)
        self.vel = (0.0, 0.0)
        self.t = 0.0
        self.phase = 0.0
        self._write_pose()
        self.renderer = mujoco.Renderer(self.model, height=720, width=1280)
        self.writer = None
        self.video_path = video_path
        self._next_video = 0.0

    def _apply(self, name):
        body, pos, tilt = CHANGES[name]
        mocap = self.model.body_mocapid[self.model.body(body).id]
        self.data.mocap_pos[mocap] = pos
        if tilt is not None:
            self.data.mocap_quat[mocap] = (math.cos(tilt / 2), math.sin(tilt / 2), 0, 0)

    def _write_pose(self):
        q = self.home.copy()
        ox, oy, oyaw = self.origin
        c, s = math.cos(oyaw), math.sin(oyaw)
        tx, ty, tyaw = self.true
        x, y, yaw = ox + c * tx - s * ty, oy + s * tx + c * ty, oyaw + tyaw
        q[:3] = x, y, 0.30
        q[3:7] = math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)
        moving = abs(self.vel[0]) + abs(self.vel[1]) > 1e-3
        if moving:
            swing = 0.25 * math.sin(self.phase)
            q[8::3] += np.array([swing, -swing, -swing, swing])
        self.data.qpos[:] = q
        mujoco.mj_forward(self.model, self.data)

    def start(self):
        self.sleep(0.5)

    def pose(self):
        return tuple(float(v) for v in self.odom)

    def true_pose(self):
        return tuple(float(v) for v in self.true)

    def command(self, vx, vy, wz):
        vx, vy, wz = clamp_velocity(self.limits, vx, vy, wz)
        self.vel = (vx, wz)

    def stop(self):
        self.vel = (0.0, 0.0)

    def render(self, camera):
        self.renderer.update_scene(self.data, camera=camera)
        return self.renderer.render().copy()

    def frame(self):
        return self.render("front")

    def now(self):
        return self.t

    def sleep(self, seconds):
        s, dt = self.sim, 0.01
        for _ in range(max(1, round(seconds / dt))):
            vx, wz = self.vel
            noise = self.rng.normal(0, s["odom_noise"], 3) if vx or wz else np.zeros(3)
            ox, oy, oyaw = self.odom
            self.odom = np.array([
                ox + vx * math.cos(oyaw) * dt + noise[0] * dt,
                oy + vx * math.sin(oyaw) * dt + noise[1] * dt,
                wrap(oyaw + wz * dt + noise[2] * dt),
            ])
            tx, ty, tyaw = self.true
            true_vx = vx * (1 - s["slip"])
            true_wz = wz * (1 + s["yaw_gain_error"]) + (s["yaw_rate_bias"] if vx or wz else 0.0)
            self.true = np.array([
                tx + true_vx * math.cos(tyaw) * dt,
                ty + true_vx * math.sin(tyaw) * dt,
                wrap(tyaw + true_wz * dt),
            ])
            self.phase += 12 * dt
            self.t += dt
            self._write_pose()
            if self.video_path and self.t >= self._next_video:
                self._video_frame()
                self._next_video = self.t + 0.1

    def _video_frame(self):
        import cv2

        wide = self.render("overview")[:, :, ::-1]
        front = self.render("front")[:, :, ::-1]
        small = cv2.resize(front, (426, 240))
        wide[10:250, -436:-10] = small
        if self.writer is None:
            self.writer = cv2.VideoWriter(str(self.video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (1280, 720))
        self.writer.write(wide)

    def close(self):
        if self.writer:
            self.writer.release()
        self.renderer.close()
