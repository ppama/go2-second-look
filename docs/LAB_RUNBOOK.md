# Lab runbook

Stop at the first failed step and fix it. Use the remote as the manual stop.

## Safety, before any motion

- [ ] Area clear of people, props outside the walking path
- [ ] Remote in hand, one person handling the Ethernet cable
- [ ] Battery charged, and the Go2 is permitted on this surface
- [ ] First moves run without the VLM

## Hardware tests, in order

1. Network: `sudo nmcli con up go2`, then `.venv/bin/python scripts/preflight.py`
2. State and camera, no motion: `.venv/bin/python scripts/check_go2.py`
3. Stand and stop: `.venv/bin/python scripts/test_motion.py --stand-only --remote-in-hand`
4. Short forward move: `.venv/bin/python scripts/test_motion.py --remote-in-hand`.
   Repeat it and check that the remote stops the robot
5. Odometry: carry or walk the Go2 1 m and compare with a tape measure
6. Stations: measure and mark them, and update `configs/mission.yaml`
7. VLM on one saved frame pair
8. Full loop

Do not run anything in `example/go2/low_level/`.

## Option: run on the Go2's onboard computer

Use this with a short cable, if the Go2 has the onboard computer. Test the remote stop first.

```bash
scripts/go2_remote.sh check       # shows Python, packages and the interface
scripts/go2_remote.sh sync        # copies code and sets the interface
ssh unitree@192.168.123.18
cd go2_second_look && tmux new -s patrol
python3 scripts/check_go2.py
python3 scripts/run_patrol.py --backend go2 --phase after --run go2_1 --reference logs/go2_ref \\
    --vlm none --truth B=fallen C=removed --record --remote-in-hand
```

Then, on the PC: `scripts/go2_remote.sh fetch`, and `scripts/revlm.py logs/go2_1`.

## Runs

```bash
# Reference patrol
.venv/bin/python scripts/run_patrol.py --backend go2 --phase before --run go2_ref --record --remote-in-hand

# Change the scene, write down the truth, then run
.venv/bin/python scripts/run_patrol.py --backend go2 --phase after --run go2_1 \
    --reference logs/go2_ref --truth B=fallen C=removed --record --remote-in-hand
```

The free tier allows 20 Robotics ER calls a day and 5 a minute. A patrol uses 3 calls.
Tune prompts on saved frames, and rerun a lost station instead of the whole patrol:

```bash
.venv/bin/python scripts/revlm.py logs/go2_1                        # failed or missing comparisons
.venv/bin/python scripts/revlm.py logs/go2_1 --mode single --stations B C   # baseline
```

After each run, measure the distance from the start mark and enter it in the table below.

| Run | Scene change | Tape return error (cm) | Notes |
|---|---|---|---|
| | | | |

After a run:

```bash
.venv/bin/python scripts/make_cards.py logs/go2_1
.venv/bin/python scripts/make_survey.py logs/go2_1
.venv/bin/python scripts/camera_to_mp4.py logs/go2_1
```

## Evaluation target

- 5 return-error runs
- 10 station comparisons: 5 changed, 5 unchanged with footprints
- Keep the failures and their saved frames for the report

`score.py` uses true poses in sim only. On hardware, its return error is odometry; use tape for the real value.
