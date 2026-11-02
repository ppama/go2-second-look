#!/usr/bin/env python
"""Turn a recorded camera folder into an MP4 at its real frame rate: camera_to_mp4.py logs/run"""
import subprocess
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
rows = [line.split(",") for line in (run_dir / "camera" / "stamps.csv").read_text().splitlines()]
if len(rows) < 2:
    raise SystemExit("not enough frames")
fps = (len(rows) - 1) / (float(rows[-1][1]) - float(rows[0][1]))
out = run_dir / "camera.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:.3f}", "-i", str(run_dir / "camera" / "%06d.jpg"),
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", str(out)], check=True)
print(f"saved {out}, {len(rows)} frames at {fps:.1f} fps")
