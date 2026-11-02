"""One folder per run: station JPEGs, odom.csv and run.json."""
import csv
import json
import time
from pathlib import Path

from PIL import Image


class RunLog:
    def __init__(self, run_dir, meta):
        self.dir = Path(run_dir)
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.data = {**meta, "stations": {}, "status": "running"}
        self._file = open(self.dir / "odom.csv", "w", newline="")
        self._csv = csv.writer(self._file)
        self._csv.writerow(["t", "x", "y", "yaw", "cmd_vx", "cmd_wz"])
        self.save()

    def odom(self, t, x, y, yaw, vx, wz):
        self._csv.writerow([f"{v:.4f}" for v in (t, x, y, yaw, vx, wz)])

    def station(self, st, frame, result):
        path = self.dir / "frames" / f"{st['id']}.jpg"
        Image.fromarray(frame).save(path, quality=92)
        self.data["stations"][st["id"]] = {
            "name": st["name"], "stamp": time.time(), "frame": str(path.relative_to(self.dir)), **result,
        }
        self.save()

    def finish(self, status, pose):
        self.data["status"] = status
        self.data["final_odom_pose"] = list(pose) if pose else None
        self._file.close()
        self.save()

    def save(self):
        tmp = self.dir / "run.json.tmp"
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.dir / "run.json")
