# Real2sim experiments

Two routes from recorded lab data to simulation. Scans, frames and renders stay private.

| Route | Input | Output | Good for | Limit |
|---|---|---|---|---|
| Mesh | TSDF mesh | MuJoCo scene with collision | Layout and route tests | Blobby views, not for VLM tests |
| Gaussian splat | RGB frames, SLAM poses, calibration | Photoreal renders near the camera path | Visual review | One moment in time, no collision |

## Gaussian splat proof of concept

- Input: 298 frames of the sandbox, with poses from the SLAM trajectory and the bag's calibration, so no COLMAP.
- Poses were checked by projecting the coloured cloud into real photos.
- Training: 15000 steps at 640x360, ending with 1,915,144 Gaussians.
- Held-out views: 30 frames never used in training, mean PSNR 23.79 dB, worst 11.62 dB.

Static parts look good. Thin and fast-changing parts, such as panel edges and the robot, are blurred.
The worst views are well below the mean. The pipeline has not been connected to the MuJoCo camera.
It shows the lab at the time of the recording, not the lab today.

Run: `scripts/splat_extract.py`, `scripts/splat_check_poses.py`, then `scripts/splat_train.py` in a separate `.venv_splat`.
