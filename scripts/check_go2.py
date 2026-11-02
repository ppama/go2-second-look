#!/usr/bin/env python
"""Read-only Go2 check: state and one camera frame. Sends no motion commands."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.go2.video.video_client import VideoClient
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

from scout.config import load_config

cfg = load_config()
msgs = []
ChannelFactoryInitialize(0, cfg["robot"]["interface"])
sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
sub.Init(lambda m: msgs.append(m), 10)
time.sleep(3)
print("state messages in 3 s:", len(msgs))
if msgs:
    m = msgs[-1]
    print("position:", list(m.position), "rpy:", list(m.imu_state.rpy), "mode:", m.mode)

video = VideoClient()
video.SetTimeout(3.0)
video.Init()
code, data = video.GetImageSample()
print("camera code:", code)
if code == 0:
    Path("check_frame.jpg").write_bytes(bytes(data))
    print("saved check_frame.jpg")
