# Provenance

Vendored from `google-deepmind/mujoco_menagerie`, subdirectory `unitree_go2/`,
commit `accb6df40a9a1d1e49eff88157f6818b63a49335` (fetched 2026-06-24).

- Upstream: https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_go2
- License: BSD-3-Clause (see `LICENSE` in this directory)
- Changes from upstream: dropped `go2.png` / `go2_mjx.png` preview images
  (not needed for simulation, ~2.4MB saved). MJCF/meshes are unmodified.
- This project: added an approximate `front` camera to `go2.xml`; removed unused scene files.
