#!/usr/bin/env python
"""Checks before a lab session. Sends nothing to the robot except ping, and no API request."""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scout.config import ROOT, load_config

cfg = load_config()
iface = cfg["robot"]["interface"]
failed = 0


def check(name, ok, hint=""):
    global failed
    failed += not ok
    print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f": {hint}" if hint and not ok else ""))


def shell(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)


try:
    carrier = Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
except OSError:
    carrier = False
check(f"adapter {iface} has link", carrier, "plug in the cable, and check the Go2 is on")
check("adapter has 192.168.123.x", "192.168.123." in shell(f"ip -4 addr show {iface}").stdout, "sudo nmcli con up go2")
check("Go2 replies to ping", shell("ping -c 2 -W 1 192.168.123.161").returncode == 0, "wait for boot, or check the address")
check("GEMINI_API_KEY set", bool(os.environ.get("GEMINI_API_KEY")), "open a new terminal, or source ~/.bashrc")
try:
    socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=5).close()
    internet = True
except OSError:
    internet = False
check("Gemini API reachable", internet, "the PC needs internet on enp4s0 or Wi-Fi")
check("at least 5 GB free", shutil.disk_usage(ROOT).free > 5e9)
for module in ("unitree_sdk2py", "cv2", "google.genai"):
    check(f"import {module}", shell(f"{sys.executable} -c 'import {module}'").returncode == 0)
print("READY" if not failed else f"{failed} check(s) failed")
sys.exit(1 if failed else 0)
