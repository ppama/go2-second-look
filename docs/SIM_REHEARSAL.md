# Simulated rehearsal

A dress rehearsal for the hardware run. Run with `scripts/rehearsal.py` and `scripts/rehearsal_gemini.py`.
**Drift values are assumptions.** Use this to find failure modes, not to predict robot performance.
Repeat the table with real measurements after the first hardware loops.

## Setup

- One reference patrol, then 48 after-patrols: 6 scenes, 2 seeds, 4 drift levels. 144 station checks.
- Every patrol ended with status complete.
- Patrol time in simulation: 47 s on average, with a 1.5 s settle at each stop and VLM calls excluded.

## Results by drift level

| Drift | Median stop shift (cm) | Max stop shift (cm) | Max yaw shift (deg) | Max true return error (cm) | Odometry return error (cm) | Pixel false alarms | Detector false alarms |
|---|---|---|---|---|---|---|---|
| base | 4 | 20 | 12 | 33 | 9.5 | 24/24 | 8/24 |
| x2 | 20 | 51 | 28 | 58 | 9.5 | 24/24 | 13/24 |
| x4 | 52 | 111 | 60 | 96 | 9.5 | 24/24 | 21/24 |
| x8 | 109 | 206 | 125 | 129 | 9.5 | 24/24 | 21/24 |

All 48 changed stations were caught by both pixel difference and the detector at every level, but
both raise so many false alarms that a positive means little.

## Gemini at twice the configured drift

| Station | Truth | Stop shift | Yaw shift | Gemini |
|---|---|---|---|---|
| B | Unchanged | 33 cm | 19 deg | No change, correct |
| C | Unchanged | 43 cm | 25 deg | No change, correct |
| B | Tower fallen | 34 cm | 20 deg | Changed, correct |

The next call hit the daily rate limit, so nothing beyond this was tested. Three stations is a very small sample.

## What this means for the hardware run

1. **Tape, not odometry.** Odometry reports under 10 cm in every run, because the controller stops
   when odometry says it arrived. It cannot show true error, which reached 33 cm at the base level.
2. **Measure real drift first.** Compare a real return with the table to pick the matching row.
3. **Working limit.** Gemini has only been tested up to about 40 cm and 25 degrees. If real stops
   exceed that, shorten the route or add a visual marker. Treat larger shifts as untested.
4. **Restart every patrol at the marked start pose.** Drift then does not build up between patrols.
5. **Fill the frame.** Keep each scene central, with margin at the edges, for yaw shift.
6. **Plan the time.** A patrol is about 1 minute in motion. With resets and a tape measurement,
   allow 5 to 10 minutes per run, as an estimate.
7. **Budget the VLM.** A patrol uses 3 calls. Collect frames first with `--vlm none`, then use `revlm.py`.
8. **Gemini stays the primary comparison.** Pixel difference and the detector are baselines only.
