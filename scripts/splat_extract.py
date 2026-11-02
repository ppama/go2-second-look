#!/usr/bin/env python
"""Extract sharp frames and camera poses from a rosbag for Gaussian splatting.

Poses come from the SLAM trajectory and the bag's camera-to-LiDAR transform, so no structure from
motion is needed. Output stays in output/splat/ and is never committed.

splat_extract.py BAG_DIR TRAJ_FILE CLOUD_PLY OUT_DIR --frames 300
"""
import argparse
import glob
import json
from pathlib import Path

import cv2
import numpy as np
import trimesh
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory
from PIL import Image
from scipy.spatial.transform import Rotation as R

TOPIC = "/camera/color/image_raw"


def matrix(translation, quat_xyzw):
    t = np.eye(4)
    t[:3, :3] = R.from_quat(quat_xyzw).as_matrix()
    t[:3, 3] = translation
    return t


p = argparse.ArgumentParser()
for name in ("bag", "traj", "cloud", "out"):
    p.add_argument(name)
p.add_argument("--frames", type=int, default=300)
args = p.parse_args()
out = Path(args.out)
(out / "images").mkdir(parents=True, exist_ok=True)

traj = np.loadtxt(args.traj)
with open(glob.glob(args.bag + "/*.mcap")[0], "rb") as f:
    reader = make_reader(f, decoder_factories=[DecoderFactory()])
    t_cam_lidar, K = None, None
    for _, _, _, msg in reader.iter_decoded_messages(topics=["/tf_static"]):
        for tf in msg.transforms:
            if tf.header.frame_id == "camera_color_optical_frame" and tf.child_frame_id == "livox_frame":
                v, q = tf.transform.translation, tf.transform.rotation
                t_cam_lidar = matrix([v.x, v.y, v.z], [q.x, q.y, q.z, q.w])
    for _, _, _, msg in reader.iter_decoded_messages(topics=["/camera/color/camera_info"]):
        K = np.array(msg.k).reshape(3, 3)
        break

    # One pass: keep the sharpest frame in each time slot.
    start, end = traj[0, 0], traj[-1, 0]
    slot = (end - start) / args.frames
    best = {}
    for _, _, _, msg in reader.iter_decoded_messages(topics=[TOPIC]):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        k = int((stamp - start) / slot)
        if not 0 <= k < args.frames:
            continue
        i = int(np.argmin(np.abs(traj[:, 0] - stamp)))
        if abs(traj[i, 0] - stamp) > 0.03:
            continue
        rgb = np.frombuffer(bytes(msg.data), np.uint8).reshape(msg.height, msg.width, -1)[:, :, :3]
        sharp = cv2.Laplacian(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var()
        if k not in best or sharp > best[k][0]:
            best[k] = (sharp, rgb.copy(), i)

frames = []
for k in sorted(best):
    _, rgb, i = best[k]
    t_world_lidar = matrix(traj[i, 1:4], traj[i, 4:8])
    t_world_cam = t_world_lidar @ np.linalg.inv(t_cam_lidar)
    name = f"{k:04d}.jpg"
    Image.fromarray(rgb).save(out / "images" / name, quality=95)
    frames.append({"file": name, "T_world_cam": t_world_cam.tolist()})

cloud = trimesh.load(args.cloud, process=False)
points = np.asarray(cloud.vertices, np.float32)
colors = np.asarray(cloud.visual.vertex_colors, np.uint8)[:, :3] if hasattr(cloud, "visual") else np.asarray(cloud.colors, np.uint8)[:, :3]
keep = np.random.default_rng(0).choice(len(points), min(len(points), 400000), replace=False)
np.savez(out / "cloud.npz", points=points[keep], colors=colors[keep])
(out / "cameras.json").write_text(json.dumps({"K": K.tolist(), "width": 1280, "height": 720, "frames": frames}))
print("frames", len(frames), "cloud", len(points))
