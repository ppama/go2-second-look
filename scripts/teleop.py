#!/usr/bin/env python
"""Manual drive with the live camera: hold keys to move, release to stop.

W/S or Up/Down forward and back. A/D or Left/Right turn in place. Q/E sidestep left and right.
Keys combine, for example W+A for a curve. 1/2/3 pick the gear. SPACE latched stop (R clears it). Esc quits.
The robot also stops when the window loses focus, the camera goes stale, or a command fails.
Only one program may command the robot: stop any patrol first. The remote stays the real safety stop.
teleop.py --remote-in-hand [--stand] [--gear 2]    teleop.py --view-only
"""
import argparse
import signal
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from scout.config import load_config
from scout.patrol import stop_robot
from scout.robot import Go2Robot, clamp_velocity

KEY_STALE_S, CAMERA_STALE_S, RELEASE_S = 0.3, 1.0, 0.06
# Forward m/s, turn rad/s, sidestep m/s. Sidestep is for manual driving only; the patrol keeps max_vy 0.
GEARS = {"1": (0.15, 0.4, 0.10), "2": (0.20, 0.5, 0.15), "3": (0.30, 0.6, 0.20)}
MAX_SIDESTEP = 0.20
KEYS = {"w": "w", "a": "a", "s": "s", "d": "d", "q": "q", "e": "e", "up": "w", "down": "s", "left": "a", "right": "d"}


class Teleop:
    """Decides the command for each control tick, and sends a stop once when motion ends."""

    def __init__(self, robot, limits, gear="2"):
        self.robot, self.limits = robot, {**limits, "max_vy": MAX_SIDESTEP}
        self.set_gear(gear)
        self.moving, self.latched, self.reason = False, False, "ready"

    def set_gear(self, gear):
        self.gear = gear
        self.speed, self.turn, self.side = GEARS[gear]

    def wanted(self, keys, key_age, camera_age):
        if self.latched:
            return (0.0, 0.0, 0.0), "STOP latched, R clears"
        if key_age > KEY_STALE_S:
            return (0.0, 0.0, 0.0), "window not responding"
        if camera_age > CAMERA_STALE_S:
            return (0.0, 0.0, 0.0), "camera stale"
        vx = self.speed * (("w" in keys) - ("s" in keys))
        vy = self.side * (("q" in keys) - ("e" in keys))
        wz = self.turn * (("a" in keys) - ("d" in keys))
        return (vx, vy, wz), "driving" if vx or vy or wz else "ready"

    def tick(self, keys, key_age, camera_age):
        (vx, vy, wz), self.reason = self.wanted(keys, key_age, camera_age)
        try:
            if vx or vy or wz:
                self.robot.command(*clamp_velocity(self.limits, vx, vy, wz))
                self.moving = True
            elif self.moving:
                self.moving = False
                stop_robot(self.robot)
        except Exception as e:
            self.latched, self.reason = True, f"command failed: {e}"
            self.moving = False
            try:
                stop_robot(self.robot)
            except Exception:
                self.reason = "STOP FAILED: USE THE REMOTE"


class App:
    def __init__(self, tk, robot, teleop, dt):
        self.tk, self.robot, self.teleop, self.dt = tk, robot, teleop, dt
        self.held, self.release = set(), {}
        self.key_stamp = self.frame_stamp = time.monotonic()
        self.frame, self.running, self.count, self.exit_reason = None, True, 0, "unknown"
        self.label = tk.Label(self.root_frame())
        self.label.pack()
        for event, handler in (("<KeyPress>", self.press), ("<KeyRelease>", self.unpress), ("<FocusOut>", self.unfocus)):
            tk.root.bind(event, handler)
        tk.root.protocol("WM_DELETE_WINDOW", lambda: self.quit("window closed"))
        threading.Thread(target=self.camera_loop, daemon=True).start()
        if teleop:
            threading.Thread(target=self.control_loop, daemon=True).start()
        self.draw()

    def root_frame(self):
        return self.tk.root

    def press(self, event):
        key = event.keysym.lower()
        key = KEYS.get(key, key)
        self.release.pop(key, None)
        if key == "escape":  # not Q, which sits next to W and A
            self.quit("Esc pressed")
        elif self.teleop and key == "space":
            self.teleop.latched = True
        elif self.teleop and key == "r":
            self.teleop.latched = False
        elif self.teleop and key in GEARS:
            self.teleop.set_gear(key)
        elif key in KEYS:
            self.held.add(key)

    def unpress(self, event):
        # X11 auto-repeat sends release then press, so a release counts only if no press follows.
        key = event.keysym.lower()
        self.release[KEYS.get(key, key)] = time.monotonic() + RELEASE_S

    def unfocus(self, _):
        self.held.clear()

    def camera_loop(self):
        while self.running:
            try:
                self.frame, self.frame_stamp = self.robot.frame(), time.monotonic()
                self.count += 1
                time.sleep(0.05)
            except Exception:
                time.sleep(0.1)

    def control_loop(self):
        while self.running:
            now = time.monotonic()
            self.teleop.tick(set(self.held), now - self.key_stamp, now - self.frame_stamp)
            time.sleep(self.dt)

    def draw(self):
        now = time.monotonic()
        self.key_stamp = now
        for key, when in list(self.release.items()):
            if now >= when:
                self.held.discard(key)
                del self.release[key]
        if self.frame is not None:
            img = Image.fromarray(self.frame).resize((960, 540))
            age = now - self.frame_stamp
            text = f"camera age {age:.1f} s   " + (f"gear {self.teleop.gear}   {self.teleop.reason}   keys {''.join(sorted(self.held))}" if self.teleop else "VIEW ONLY")
            ImageDraw.Draw(img).rectangle((0, 0, 960, 22), fill="black")
            ImageDraw.Draw(img).text((6, 5), text, fill="red" if age > CAMERA_STALE_S or (self.teleop and self.teleop.latched) else "yellow")
            self.photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self.photo)
        self.tk.root.after(33, self.draw)

    def quit(self, reason="signal", *_):
        self.exit_reason = reason if isinstance(reason, str) else f"signal {reason}"
        self.running = False
        self.tk.root.quit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--remote-in-hand", action="store_true")
    p.add_argument("--view-only", action="store_true", help="camera only, sends no commands")
    p.add_argument("--stand", action="store_true", help="stand first")
    p.add_argument("--gear", choices=GEARS, default="2")
    p.add_argument("--seconds", type=float, help="close after this long")
    args = p.parse_args()
    if not args.view_only and not args.remote_in_hand:
        raise SystemExit("Needs --remote-in-hand: area clear, remote held, cable handled, no patrol running.")

    import tkinter

    cfg = load_config()
    robot = Go2Robot(cfg)
    if args.stand and not args.view_only:
        robot.start()
    teleop = None if args.view_only else Teleop(robot, cfg["limits"], args.gear)

    class Window:
        root = tkinter.Tk()
        Label = tkinter.Label

    Window.root.title("Go2 teleop" if teleop else "Go2 view only")
    app = App(Window, robot, teleop, cfg["limits"]["control_dt_s"])
    signal.signal(signal.SIGTERM, app.quit)
    signal.signal(signal.SIGHUP, app.quit)
    signal.signal(signal.SIGINT, app.quit)
    if args.seconds:
        Window.root.after(int(args.seconds * 1000), lambda: app.quit("--seconds limit"))
    try:
        Window.root.mainloop()
    finally:
        app.running = False
        time.sleep(0.2)
        if teleop:
            stop_robot(robot)
        print("camera frames:", app.count, "exit:", app.exit_reason)


if __name__ == "__main__":
    main()
