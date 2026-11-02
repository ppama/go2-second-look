"""Saves camera JPEGs for the video. A recorder failure never affects the patrol."""
import threading
import time
from pathlib import Path


class CameraRecorder:
    def __init__(self, grab, out_dir, rate_hz=10.0):
        self.grab, self.period = grab, 1.0 / rate_hz
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.error = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        with open(self.dir / "stamps.csv", "w") as stamps:
            while not self._stop.is_set():
                t0 = time.monotonic()
                try:
                    data = self.grab()
                    (self.dir / f"{self.count:06d}.jpg").write_bytes(data)
                    stamps.write(f"{self.count},{time.time():.3f}\n")
                    self.count += 1
                except Exception as e:
                    self.error = repr(e)
                self._stop.wait(max(0.0, self.period - (time.monotonic() - t0)))

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)
        print(f"camera frames: {self.count}" + (f", last error: {self.error}" if self.error else ""))
