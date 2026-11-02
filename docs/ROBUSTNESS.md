# Robustness experiments

Simulation results, plus one test on recorded real frames. None of this has run on the Go2.

## Visual re-alignment

At each stop, `--realign` matches the live view to the reference frame with SIFT, estimates heading
and scale, and makes small corrections. Weak matches and large corrections are refused. It does
not correct sideways error. It is off by default.

**Real frames:** 80 pairs of real sandbox frames, with SLAM poses as ground truth, median true turn
5.9 deg: all 80 matched, median heading error 1.7 deg, 90th percentile 6.0 deg, correct direction
in 95%. This checks the estimate only, not a corrected robot stop.

**Simulation:** before and after re-alignment, 36 stations per level.

| Drift | Median yaw shift (deg) | Max yaw shift (deg) | Median stop shift (cm) | Detector false alarms | Detector caught |
|---|---|---|---|---|---|
| base | 2.1 to 1.9 | 12 to 12 | 4 to 4 | 8/24 to 5/24 | 12/12 |
| x2 | 8.2 to 8.0 | 28 to 31 | 20 to 21 | 13/24 to 13/24 | 12/12 |
| x4 | 21.3 to 21.5 | 60 to 61 | 52 to 53 | 21/24 to 20/24 | 12/12 |
| x8 | 47.4 to 49.0 | 125 to 125 | 109 to 110 | 21/24 to 23/24 | 12/12 |

**Verdict: not ready to use.** With the guard, re-alignment does almost nothing in simulation. It
avoids harm, but most of the benefit is gone too. Without the guard, the base level improved more
(maximum yaw shift 11.5 to 4.7 deg, detector false alarms 8 to 0 of 24), but at twice the drift the
maximum yaw shift grew from 28 to 41 deg, and it was worse again at higher levels. Keep `--realign`
off for the main run.

Patrol time rose from 47 s to 51 s. Stop position barely changes, because
sideways error is not corrected. Results for the higher levels show the limit of the method.
The confidence thresholds were chosen on these same runs, so treat them as tuned values, not
an independent test.

## Fault injection

Run `scripts/fault_matrix.py`. Each case must end with the robot stopped and the run logged.

| Fault | Final status | Robot stopped | Stations logged |
|---|---|---|---|
| Nothing, as a control | complete | yes | 3 |
| Camera request fails at station B | aborted | yes | 1 |
| Camera returns an undecodable frame | aborted | yes | 1 |
| State messages stop mid-route | aborted | yes | 1 |
| Move command returns an error | aborted | yes | 1 |
| Robot is blocked and stops moving | aborted | yes | 1 |
| Operator presses Ctrl-C | aborted | yes | 1 |
| Process is killed, as when SSH drops | aborted | yes | 1 |
| StopMove fails twice before working | complete | yes | 3 |
| VLM rate limited at every station | complete | yes | 3 |
| VLM server overloaded | complete | yes | 3 |
| VLM returns text that is not JSON | complete | yes | 3 |
| VLM reply asks the robot to move | complete | yes | 3 |

13 of 13 passed. The first run failed one case, and that exposed a real bug: stops between legs did
not retry, so a brief StopMove failure ended the patrol. All stops now retry.

"Stopped" means the code issued a stop and its simulated velocity is zero. How the real Go2 reacts
to a lost link or a killed process is untested, so the remote stays the real safety stop.
