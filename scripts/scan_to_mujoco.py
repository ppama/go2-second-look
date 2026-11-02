#!/usr/bin/env python
"""Turn a coloured TSDF mesh into a MuJoCo scene: visual mesh, collision heightfield, and a patrol config.

Unknown space is treated as an obstacle, so a route can never leave the scanned floor.

scan_to_mujoco.py /path/to/mesh.ply --name lab [--faces 400000]
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import fast_simplification
import trimesh
import yaml
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

CELL = 0.05          # heightfield resolution, m
OBSTACLE_H = 0.6     # heightfield wall height, m
CEILING_CROP = 1.9   # removed above this height so a top view can see in
BODY = (0.12, 0.7)   # height band that can touch a walking Go2


def fit_floor(points, rng, tries=400):
    """RANSAC for the largest near-horizontal plane in the lower half of the scan."""
    low = points[points[:, 2] < np.median(points[:, 2])]
    sample = low[rng.choice(len(low), min(len(low), 300000), replace=False)]
    best, best_count = None, -1
    for _ in range(tries):
        a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        if n[2] < 0:
            n = -n
        if n[2] < 0.95:
            continue
        count = int((np.abs((sample - a) @ n) < 0.03).sum())
        if count > best_count:
            best, best_count = (n, a), count
    n, a = best
    inliers = sample[np.abs((sample - a) @ n) < 0.03]
    centre = inliers.mean(axis=0)
    n = np.linalg.svd(inliers - centre)[2][2]
    return (n if n[2] > 0 else -n), centre, best_count / len(sample)


def level(points, n, centre):
    """Rotate so the floor normal is +z and the floor sits at z = 0."""
    v = np.cross(n, [0, 0, 1])
    s, c = np.linalg.norm(v), n[2]
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    rot = np.eye(3) + k + k @ k * ((1 - c) / max(s * s, 1e-12))
    return (points - centre) @ rot.T


def morton_cell(rank, bits):
    """Rank along a Z curve to a 2D cell, so faces close in space stay close in the texture."""
    x, y = np.zeros_like(rank), np.zeros_like(rank)
    for b in range(bits):
        x |= ((rank >> (2 * b)) & 1) << b
        y |= ((rank >> (2 * b + 1)) & 1) << b
    return x, y


def spatial_order(centres):
    q = ((centres - centres.min(0)) / max(np.ptp(centres, axis=0).max(), 1e-9) * 1023).astype(np.int64)
    code = np.zeros(len(q), np.int64)
    for b in range(10):
        for axis in range(3):
            code |= ((q[:, axis] >> b) & 1) << (3 * b + axis)
    return np.argsort(code)


def bake(vertices, faces, source_tree, source_colors):
    """One texture pixel per face. MuJoCo has no vertex colours, so this carries the scan colour."""
    faces = faces[spatial_order(vertices[faces].mean(axis=1))]
    centres = vertices[faces].mean(axis=1)
    _, nearest = source_tree.query(centres, k=4, workers=-1)
    colors = source_colors[nearest].mean(axis=1).astype(np.uint8)
    bits = math.ceil(math.log2(max(len(faces), 2)) / 2)
    size = 1 << bits
    x, y = morton_cell(np.arange(len(faces), dtype=np.int64), bits)
    image = np.zeros((size, size, 3), np.uint8)
    image[y, x] = colors
    u, v = (x + 0.5) / size, 1 - (y + 0.5) / size
    return faces, np.c_[u, v], image


def write_obj(path, vertices, faces, uv):
    corners = vertices[faces].reshape(-1, 3)
    with open(path, "w") as f:
        np.savetxt(f, corners, fmt="v %.4f %.4f %.4f")
        np.savetxt(f, np.repeat(uv, 3, axis=0), fmt="vt %.6f %.6f")
        ids = np.arange(1, len(corners) + 1).reshape(-1, 3)
        np.savetxt(f, np.repeat(ids, 2, axis=1), fmt="f %d/%d %d/%d %d/%d")


def free_space(points):
    lo = np.floor(points[:, :2].min(0) / CELL).astype(int) - 4
    idx = np.floor(points[:, :2] / CELL).astype(int) - lo
    shape = idx.max(0) + 5
    floor = np.zeros(shape, bool)
    body = np.zeros(shape, bool)
    z = points[:, 2]
    near_floor = np.abs(z) < 0.06
    floor[idx[near_floor, 0], idx[near_floor, 1]] = True
    hit = (z > BODY[0]) & (z < BODY[1])
    body[idx[hit, 0], idx[hit, 1]] = True
    floor = ndimage.binary_closing(floor, iterations=2) & ~body
    floor = ndimage.binary_opening(floor, iterations=1)
    labels, count = ndimage.label(floor)
    if count == 0:
        raise SystemExit("no floor found")
    sizes = ndimage.sum(floor, labels, range(1, count + 1))
    free = labels == 1 + int(np.argmax(sizes))
    return free, lo * CELL


def clear_line(clearance, a, b, margin):
    n = max(2, int(np.hypot(*(b - a)) / CELL) + 1)
    cells = np.round(np.linspace(a, b, n)).astype(int)
    return clearance[cells[:, 0], cells[:, 1]].min() * CELL >= margin


def plan_stations(free, rng, margin=0.35, count=3):
    """Pick a start and a closed loop of stations, all joined by clear straight lines."""
    clearance = ndimage.distance_transform_edt(free)
    cells = np.argwhere(clearance * CELL >= margin)
    if len(cells) < 20:
        return None
    start = np.unravel_index(np.argmax(clearance), free.shape)
    start = np.array(start)
    for _ in range(40000):
        pick = cells[rng.choice(len(cells), count, replace=False)]
        route = [start, *pick, start]
        lengths = [np.hypot(*(b - a)) * CELL for a, b in zip(route, route[1:])]
        if min(lengths) < 0.8 or max(lengths) > 2.5:
            continue
        if all(clear_line(clearance, a, b, margin) for a, b in zip(route, route[1:])):
            return start, pick
    return None


def view_yaw(free, cell):
    """Face the direction whose nearest obstacle is about 1.5 m away, so the view has a scene."""
    best, best_score = 0.0, 1e9
    for yaw in np.linspace(-math.pi, math.pi, 24, endpoint=False):
        d = 0.0
        while d < 4.0:
            d += CELL
            i = int(cell[0] + d / CELL * math.cos(yaw))
            j = int(cell[1] + d / CELL * math.sin(yaw))
            if not (0 <= i < free.shape[0] and 0 <= j < free.shape[1]) or not free[i, j]:
                break
        if abs(d - 1.5) < best_score:
            best, best_score = yaw, abs(d - 1.5)
    return float(best)


def scene_xml(name, size_x, size_y, cx, cy, floor_rgb, tex_name):
    r, g, b = [c / 255 for c in floor_rgb]
    fov = 2 * math.degrees(math.atan2(max(size_x, size_y) * 1.05, 2 * 7.0))
    return f"""<mujoco model="{name} scan">
  <include file="assets/go2/go2.xml"/>
  <visual>
    <headlight diffuse="0.45 0.45 0.45" ambient="0.75 0.75 0.75" specular="0 0 0"/>
    <global offwidth="1280" offheight="720"/>
  </visual>
  <asset>
    <mesh name="scan" file="../../../generated/scan_{name}/scan.obj" inertia="shell"/>
    <texture name="scan" type="2d" file="generated/scan_{name}/{tex_name}"/>
    <material name="scan" texture="scan" specular="0" shininess="0"/>
    <hfield name="collision" file="../../../generated/scan_{name}/collision.bin" size="{size_x / 2} {size_y / 2} {OBSTACLE_H} 0.01"/>
  </asset>
  <worldbody>
    <geom type="plane" size="40 40 0.1" pos="{cx} {cy} -0.015" rgba="{r:.3f} {g:.3f} {b:.3f} 1" contype="0" conaffinity="0"/>
    <geom type="mesh" mesh="scan" material="scan" contype="0" conaffinity="0" group="0"/>
    <geom type="hfield" hfield="collision" pos="{cx} {cy} 0" rgba="1 0 0 0.25" group="3"/>
    <camera name="overview" pos="{cx} {cy} 7" xyaxes="1 0 0 0 1 0" fovy="{fov:.1f}"/>
  </worldbody>
</mujoco>
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mesh")
    p.add_argument("--name", required=True)
    p.add_argument("--faces", type=int, default=400000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)

    mesh = trimesh.load(args.mesh, process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SystemExit("input has no faces")
    colors = np.asarray(mesh.visual.vertex_colors)[:, :3]
    points = np.asarray(mesh.vertices, dtype=np.float64)
    n, centre, inlier_share = fit_floor(points, rng)
    levelled = level(points, n, centre)
    levelled -= np.array([*np.median(levelled[np.abs(levelled[:, 2]) < 0.05, :2], axis=0), 0])

    keep = (levelled[:, 2] > -0.25) & (levelled[:, 2] < CEILING_CROP)
    face_keep = keep[mesh.faces].all(axis=1)
    remap = np.cumsum(keep) - 1
    crop_v, crop_f, crop_c = levelled[keep], remap[mesh.faces[face_keep]], colors[keep]

    target = min(1.0, args.faces / max(len(crop_f), 1))
    vertices, faces = fast_simplification.simplify(crop_v.astype(np.float32), crop_f.astype(np.int32), 1 - target)
    tree = cKDTree(crop_v)
    faces, uv, image = bake(np.asarray(vertices, float), np.asarray(faces), tree, crop_c)

    free, origin = free_space(crop_v)
    size = np.array(free.shape) * CELL
    cx, cy = origin + size / 2
    height = (~free).astype(np.float32).T

    out = ROOT / "sim" / "generated" / f"scan_{args.name}"
    out.mkdir(parents=True, exist_ok=True)
    write_obj(out / "scan.obj", np.asarray(vertices, float), faces, uv)
    Image.fromarray(image).save(out / "scan.png")
    with open(out / "collision.bin", "wb") as f:
        np.array(height.shape, np.int32).tofile(f)
        height.astype(np.float32).tofile(f)
    Image.fromarray((np.flipud(free.T) * 255).astype(np.uint8)).save(out / "free.png")
    floor_rgb = np.median(crop_c[np.abs(crop_v[:, 2]) < 0.05], axis=0)
    scene = ROOT / "sim" / f"scan_{args.name}.xml"
    scene.write_text(scene_xml(args.name, size[0], size[1], cx, cy, floor_rgb, "scan.png"))

    meta = {
        "source": Path(args.mesh).parent.name, "faces_in": int(len(mesh.faces)), "faces_out": int(len(faces)),
        "floor_inlier_share": round(float(inlier_share), 3), "floor_normal": [round(float(v), 4) for v in n],
        "extent_m": [round(float(v), 2) for v in size], "free_area_m2": round(float(free.sum() * CELL * CELL), 2),
    }
    plan = plan_stations(free, rng)
    if plan:
        start, picks = plan
        cell_xy = lambda c: origin + (np.asarray(c) + 0.5) * CELL
        sx, sy = cell_xy(start)
        yaw0 = 0.0
        stations = []
        for k, cell in enumerate(picks):
            x, y = cell_xy(cell)
            stations.append({"id": "ABC"[k], "name": f"scan view {'ABC'[k]}", "x": round(float(x - sx), 3),
                             "y": round(float(y - sy), 3), "yaw": round(view_yaw(free, cell), 3)})
        from scout.config import load_config

        cfg = load_config()
        cfg["stations"] = stations
        cfg["sim"]["scene"] = f"scan_{args.name}.xml"
        cfg["sim"]["origin"] = [round(float(sx), 3), round(float(sy), 3), yaw0]
        (ROOT / "sim" / "generated" / f"scan_{args.name}" / "mission.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
        meta["route"] = "closed loop found"
    else:
        meta["route"] = "no clear loop"
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
