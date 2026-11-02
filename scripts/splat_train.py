#!/usr/bin/env python
"""Train a Gaussian splat from extracted frames. Every 10th frame is held out for scoring.

Runs in .venv_splat. Results go to output/splat/, which is never committed.
splat_train.py output/splat/sandbox --steps 15000
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization
from gsplat.strategy import DefaultStrategy
from PIL import Image
from scipy.spatial import cKDTree

SCALE = 2  # train at 640x360


def load(root):
    cam = json.loads((root / "cameras.json").read_text())
    K = np.array(cam["K"], np.float32)
    K[:2] /= SCALE
    images, w2c = [], []
    for frame in cam["frames"]:
        image = Image.open(root / "images" / frame["file"]).convert("RGB").resize((1280 // SCALE, 720 // SCALE), Image.Resampling.LANCZOS)
        images.append(np.asarray(image, np.float32) / 255)
        w2c.append(np.linalg.inv(np.array(frame["T_world_cam"], np.float32)))
    return torch.tensor(np.stack(images)), torch.tensor(np.stack(w2c), dtype=torch.float32), torch.tensor(K)


def ssim(a, b):
    """a and b are NCHW."""
    x = torch.arange(11, dtype=torch.float32, device=a.device) - 5
    g = torch.exp(-x * x / 4.5)
    g = (g / g.sum())[None, None]
    w = (g.transpose(1, 2) @ g).expand(3, 1, 11, 11)
    pad = 5
    mu_a, mu_b = F.conv2d(a, w, padding=pad, groups=3), F.conv2d(b, w, padding=pad, groups=3)
    var_a = F.conv2d(a * a, w, padding=pad, groups=3) - mu_a ** 2
    var_b = F.conv2d(b * b, w, padding=pad, groups=3) - mu_b ** 2
    cov = F.conv2d(a * b, w, padding=pad, groups=3) - mu_a * mu_b
    return (((2 * mu_a * mu_b + 1e-4) * (2 * cov + 9e-4)) / ((mu_a ** 2 + mu_b ** 2 + 1e-4) * (var_a + var_b + 9e-4))).mean()


def render(params, w2c, K, w, h):
    return rasterization(
        params["means"], F.normalize(params["quats"], dim=-1), torch.exp(params["scales"]), torch.sigmoid(params["opacities"]),
        torch.sigmoid(params["colors"]), w2c, K, w, h, sh_degree=None, render_mode="RGB", packed=False,
    )


def interpolate(a, b, t):
    """Pose between two camera-to-world matrices, for a smooth flythrough."""
    out = a * (1 - t) + b * t
    u, _, vh = np.linalg.svd(out[:3, :3])
    out[:3, :3] = u @ vh
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--steps", type=int, default=15000)
    args = p.parse_args()
    root = Path(args.root)
    device = "cuda"
    images, w2c, K = load(root)
    h, w = images.shape[1:3]
    test = np.arange(len(images)) % 10 == 5
    train_ids, test_ids = np.where(~test)[0], np.where(test)[0]
    centres = torch.linalg.inv(w2c)[:, :3, 3]
    scene = float((centres - centres.mean(0)).norm(dim=1).max()) * 1.1

    cloud = np.load(root / "cloud.npz")
    points = cloud["points"].astype(np.float32)
    dist = cKDTree(points).query(points, k=4)[0][:, 1:].mean(1)
    rgb = np.clip(cloud["colors"].astype(np.float32) / 255, 0.02, 0.98)
    n = len(points)
    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(torch.tensor(points)),
        "scales": torch.nn.Parameter(torch.tensor(np.log(np.clip(dist, 1e-4, 0.2)).astype(np.float32))[:, None].repeat(1, 3)),
        "quats": torch.nn.Parameter(torch.randn(n, 4)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((n,), 0.1))),
        "colors": torch.nn.Parameter(torch.logit(torch.tensor(rgb))),
    }).to(device)
    lrs = {"means": 1.6e-4 * scene, "scales": 0.01, "quats": 0.001, "opacities": 0.05, "colors": 0.005}
    optimizers = {k: torch.optim.Adam([params[k]], lr=lr, eps=1e-15) for k, lr in lrs.items()}
    sched = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], 0.01 ** (1 / args.steps))
    strategy = DefaultStrategy(verbose=False)
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene)

    images, w2c, K = images.to(device), w2c.to(device), K.to(device)
    rng = np.random.default_rng(0)
    for step in range(args.steps):
        i = int(rng.choice(train_ids))
        out, _, info = render(params, w2c[i:i + 1], K[None], w, h)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        pred, gt = out.clamp(0, 1), images[i:i + 1]
        loss = 0.8 * (pred - gt).abs().mean() + 0.2 * (1 - ssim(pred.permute(0, 3, 1, 2), gt.permute(0, 3, 1, 2)))
        loss.backward()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=False)
        for opt in optimizers.values():
            opt.step()
            opt.zero_grad(set_to_none=True)
        sched.step()
        if step % 1000 == 0:
            print(step, round(loss.item(), 4), len(params["means"]), flush=True)

    with torch.no_grad():
        psnrs, panels = [], []
        for k, i in enumerate(test_ids):
            out, _, _ = render(params, w2c[i:i + 1], K[None], w, h)
            pred = out[0].clamp(0, 1)
            psnrs.append(float(-10 * torch.log10(((pred - images[i]) ** 2).mean())))
            if k in (3, 12, 21):
                panels.append(torch.cat([images[i], pred], dim=1).cpu().numpy())
        Image.fromarray((np.vstack(panels) * 255).astype(np.uint8)).save(root / "heldout.png")
        result = {"gaussians": len(params["means"]), "heldout_frames": len(test_ids), "train_frames": len(train_ids),
                  "heldout_psnr_mean": round(float(np.mean(psnrs)), 2), "heldout_psnr_min": round(float(np.min(psnrs)), 2), "steps": args.steps}
        (root / "splat_results.json").write_text(json.dumps(result, indent=2))
        print(result, flush=True)

        c2w = torch.linalg.inv(w2c).cpu().numpy()
        frames = root / "path"
        frames.mkdir(exist_ok=True)
        count = 0
        for a, b in zip(c2w[::4][:-1], c2w[::4][1:]):
            for t in np.linspace(0, 1, 6, endpoint=False):
                pose = torch.tensor(np.linalg.inv(interpolate(a, b, t)), dtype=torch.float32, device=device)
                out, _, _ = render(params, pose[None], K[None], w, h)
                Image.fromarray((out[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)).save(frames / f"{count:05d}.jpg", quality=92)
                count += 1
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", str(frames / "%05d.jpg"), "-pix_fmt", "yuv420p", str(root / "flythrough.mp4")], check=True)
    torch.save({k: v.detach().cpu() for k, v in params.items()}, root / "splat.pt")
    print("done", count, flush=True)


if __name__ == "__main__":
    main()
