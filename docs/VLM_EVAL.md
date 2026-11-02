# VLM evaluation in simulation

All results here are simulation. The VLM reports only and never commands motion.

## Mainline: MuJoCo site environment

Same 144 frame pairs as pixel difference and the detector: 12 after-patrols at each of four drift
levels, 3 stations each (12 changed, 24 unchanged per level). Model: local `qwen3.6:latest` through
Ollama, temperature 0.1. About 1.5 s per call on this PC. Drift values are assumptions.
Run: `scripts/vlm_eval.py --side-by-side --out logs/vlm_eval/side.json`, then `scripts/vlm_eval_report.py`.

| Drift | VLM side-by-side: caught / false alarms | Detector | Pixel | VLM change type right | VLM hazard flagged |
|---|---|---|---|---|---|
| base | 12/12, 7/24 | 12/12, 8/24 | 12/12, 24/24 | 12/12 | 4/12 |
| x2 | 12/12, 17/24 | 12/12, 13/24 | 12/12, 24/24 | 10/12 | 1/12 |
| x4 | 12/12, 20/24 | 12/12, 21/24 | 12/12, 24/24 | 6/12 | 0/12 |
| x8 | 12/12, 22/24 | 12/12, 21/24 | 12/12, 24/24 | 5/12 | 0/12 |

Single-frame baseline at base drift: 0/12 caught, 0/24 false alarms. The model needs the reference.

Known-answer controls: side-by-side 12/12. Identical, different-station and swapped pairs.

### Why two-image input was rejected

Sending two separate images looked good (12/12 caught, 12/24 false alarms at base), but it was not
reading the change. False alarms were 0/48 at A, 21/24 at B and 24/24 at C, and all true changes are at
B or C, so it mostly answered by station. Controls were 7/12: all three different-station pairs were
called unchanged. In a check on scan frames, an identical pair was called changed and the model
described two images as one scene. Do not report the two-image catch rate.

### Limits

- Catches at x4 and x8 are weak evidence: stops are far off and the object can leave the view, so the
  model may report a missing scene, not the change. Change type accuracy falls for this reason.
- False alarms grow with stop error. Many are objects entering at an image edge.
- Boxes are loose and sometimes miss the object. Do not report box accuracy.
- Each view in the composite has about half the width of a two-image input.
- The hazard flag is unreliable with this model.
- These pairs are not independent: 12 runs per level over a few fixed scenes. One sim look only.

## Better input: 1600 px and overlap warp

The after frame is warped onto the reference with SIFT and unshared area is greyed, so an object at an
image edge is hidden from the model. Only the image changes: a wrong match costs a wrong report, never
a wrong motion. If no match is trusted (8 inliers, half the view shared), the raw views are compared.
Declining was tried first and rejected, because it hid real changes. Matching worked on 35/36 stops at
base, 20/36 at x2, and 15/36 at x4 and x8.

Settings were chosen on the seed 101 runs and fixed. Reported on the 18 unseen seed 202 stations per
level (6 changed, 12 unchanged). Controls 12/12.
`scripts/vlm_eval.py --side-by-side --seeds 202 --overlap --width 1600 --out logs/vlm_eval/final_test.json`

| Drift | Final: caught / false alarms | 800 px side-by-side false alarms | Detector | Pixel | Type right | Hazard |
|---|---|---|---|---|---|---|
| base | 6/6, 3/12 | 3/12 | 5/12 | 12/12 | 6/6 | 3/6 |
| x2 | 6/6, 7/12 | 8/12 | 6/12 | 12/12 | 5/6 | 1/6 |
| x4 | 6/6, 9/12 | 11/12 | 11/12 | 12/12 | 3/6 | 0/6 |
| x8 | 6/6, 9/12 | 12/12 | 11/12 | 12/12 | 3/6 | 0/6 |

The gain is modest. It helps only at large drift, and no gain shows at base. Seed 101 looked better
(2/12 at base, 4/12 at x2; one miss at x8), and those were tuning runs. Differences of a pair or two are noise.

End-to-end patrol on new seeds, `--vlm ollama`, tower fallen at B and block removed at C: 3/3 stations
right, 1/3 wrong on single frame, 6 VLM calls, true return 27 cm, odometry 9 cm. One run only.

## Gemini Robotics ER on the same site

Earlier: 12/12 on site stations (one run used an older prompt), and 3/3 on x2/x4 drift pairs. On
2026-11-01 one fallen-tower pair was right on type, hazard and location. Small sample, not a head-to-head
with the 144 pairs: free-tier quota is used up.

## Separate: scan-based real2sim room

Rough TSDF mesh, not used for the mainline numbers. An orange box was added 1.3 m ahead of station B
(`scripts/vlm_scan_examples.py room0613a`), an easy positive. 18 pairs with side-by-side input: 3/3
caught, 0/15 false alarms. Gemini: one unchanged pair right. The sample is small, and all three
positives are the same object.
