# Sim-trained change detector

An offline baseline for the Gemini comparison. It reads saved frames and never controls the robot.

| Item | Choice |
|---|---|
| Model | Siamese ResNet18 from ImageNet weights, using feature difference |
| Training data | Randomized MuJoCo pairs, half changed |
| Changes | Object added, removed, moved or fallen |
| Distractors | Viewpoint jitter, light change, fake tracks |
| Output | Probability that the scene changed |

## Reproduce

```bash
.venv/bin/python scripts/detector_data.py 6000
.venv/bin/python scripts/detector_train.py
.venv/bin/python scripts/detect_pairs.py logs/run1 logs/run2
```

## Results

| Test set | Correct | False alarms | Missed |
|---|---|---|---|
| 600 simulated pairs from the training scene type | 87.3% | 21 | 55 |
| 12 stations from the site scene, not used in training | 7 of 12 | 5 | 0 |
| Real frames | [not tested yet] | | |

On the 12 site stations, it caught all 4 real changes but raised false alarms on 5 of 8 unchanged
stations. Gemini was correct on all 12 of the same stations. Only a small sample, and one of the
Gemini runs used an earlier prompt. Training took about 90 seconds in total with data generation.

High accuracy on simulated test pairs says little about real frames. Only real frames can show
whether it transfers.
