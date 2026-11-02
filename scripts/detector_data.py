#!/usr/bin/env python
"""Render randomized before/after pairs for the change detector.

Scene, colours and light vary widely between pairs. Within a pair only viewpoint, light and sand
tracks vary, unless the label is "changed", when one visible object is altered.
"""
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = Path(__file__).resolve().parent.parent

import mujoco
import numpy as np
from PIL import Image

N_OBJ, N_TRACK = 10, 4
HIDDEN = (0, 0, -5)
HALF_FOV = math.radians(48)


def quat_z(yaw):
    return (math.cos(yaw / 2), 0, 0, math.sin(yaw / 2))


class Renderer:
    def __init__(self):
        self.m = mujoco.MjModel.from_xml_path(str(ROOT / "sim" / "train_scene.xml"))
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, height=180, width=320)
        self.mid = {b: self.m.body_mocapid[self.m.body(b).id] for b in ["rig"] + [f"o{i}" for i in range(N_OBJ)] + [f"t{i}" for i in range(N_TRACK)]}

    def set_scene(self, rng):
        m = self.m
        tint = rng.uniform(0.35, 0.95) * rng.uniform(0.8, 1.2, 3)
        m.mat_rgba[m.material("ground").id] = (*np.clip(tint, 0, 1), 1)
        m.geom_rgba[m.geom("wall").id] = (*rng.uniform(0.2, 0.9, 3), 1)
        for i in range(N_OBJ):
            g = m.geom(f"g{i}").id
            s = rng.uniform(0.06, 0.28, 3)
            if i <= 3:
                m.geom_size[g] = s
            elif i <= 6:
                m.geom_size[g] = (s[0], s[1] * 1.5, 0)
            else:
                m.geom_size[g] = s
            m.geom_rgba[g] = (*rng.uniform(0, 1, 3), 1)

    def place(self, rng):
        """Object layout in front of the origin. Returns name -> (pos, quat)."""
        layout = {}
        for i in rng.choice(N_OBJ, rng.integers(2, 8), replace=False):
            layout[f"o{i}"] = self.spot(rng, i)
        return layout

    def spot(self, rng, i):
        r, a = rng.uniform(0.9, 3.0), rng.uniform(-0.65, 0.65)
        height = self.m.geom_size[self.m.geom(f"g{i}").id][2 if i <= 3 or i >= 7 else 1]
        return np.array([r * math.sin(a), r * math.cos(a), height]), np.array(quat_z(rng.uniform(0, 3.14)))

    def render(self, layout, rng, base_cam, base_light, jitter):
        for i in range(N_OBJ):
            self.d.mocap_pos[self.mid[f"o{i}"]] = HIDDEN
        for name, (pos, quat) in layout.items():
            self.d.mocap_pos[self.mid[name]] = pos
            self.d.mocap_quat[self.mid[name]] = quat
        for i in range(N_TRACK):
            on = jitter and rng.random() < 0.7
            r, a = rng.uniform(0.5, 2), rng.uniform(-0.7, 0.7)
            self.d.mocap_pos[self.mid[f"t{i}"]] = (r * math.sin(a), r * math.cos(a), 0.003) if on else HIDDEN
        x, y, yaw = base_cam
        if jitter:
            x, y, yaw = x + rng.normal(0, 0.05), y + rng.normal(0, 0.05), yaw + rng.normal(0, 0.05)
        self.d.mocap_pos[self.mid["rig"]] = (x, y, 0.33)
        self.d.mocap_quat[self.mid["rig"]] = quat_z(yaw)
        light = base_light * (rng.uniform(0.9, 1.1) if jitter else 1.0)
        self.m.light_diffuse[0] = light
        mujoco.mj_forward(self.m, self.d)
        self.r.update_scene(self.d, camera="cam")
        return self.r.render().copy()


def change(rend, layout, rng):
    """Alter one object and return the new layout and the kind of change."""
    new = dict(layout)
    kind = rng.choice(["added", "removed", "moved", "fallen"])
    names = list(layout)
    if kind == "added":
        free = [i for i in range(N_OBJ) if f"o{i}" not in layout]
        if free:
            i = int(rng.choice(free))
            new[f"o{i}"] = rend.spot(rng, i)
            return new, kind
        kind = "removed"
    name = str(rng.choice(names))
    if kind == "removed" and len(names) > 1:
        del new[name]
        return new, kind
    pos, quat = layout[name]
    if kind == "fallen":
        i = int(name[1:])
        size = rend.m.geom_size[rend.m.geom(f"g{i}").id]
        flat = np.array([math.cos(0.785), math.sin(0.785), 0, 0])
        new[name] = (np.array([pos[0], pos[1], max(size[0], 0.06)]), flat)
        return new, "fallen"
    a = rng.uniform(0, 6.28)
    d = rng.uniform(0.3, 0.7)
    new[name] = (pos + np.array([d * math.cos(a), d * math.sin(a), 0]), quat)
    return new, "moved"


def split(rend, name, count, seed, out):
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    labels = []
    for k in range(count):
        rend.set_scene(rng)
        layout = rend.place(rng)
        cam = (rng.normal(0, 0.05), rng.normal(0, 0.05), rng.normal(0, 0.1))
        light = rng.uniform(0.3, 0.8)
        positive = k % 2 == 1
        after, kind = change(rend, layout, rng) if positive else (layout, "none")
        a = rend.render(layout, rng, cam, light, jitter=False)
        b = rend.render(after, rng, cam, light, jitter=True)
        Image.fromarray(a).save(folder / f"{k:05d}_a.jpg", quality=90)
        Image.fromarray(b).save(folder / f"{k:05d}_b.jpg", quality=90)
        labels.append({"id": k, "changed": positive, "kind": str(kind)})
    (folder / "labels.json").write_text(json.dumps(labels))
    print(name, count, flush=True)


if __name__ == "__main__":
    out = ROOT / "output" / "detector" / "data"
    rend = Renderer()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    split(rend, "train", n, 1, out)
    split(rend, "val", n // 10, 2, out)
    split(rend, "test", n // 10, 3, out)
