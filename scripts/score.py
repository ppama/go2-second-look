#!/usr/bin/env python
"""Score after-runs against their true labels: score.py logs/run1 logs/run2 ..."""
import json
import math
import sys
from pathlib import Path


def score(rows):
    tp = sum(p and t for p, t in rows)
    fp = sum(p and not t for p, t in rows)
    fn = sum(t and not p for p, t in rows)
    tn = sum(not p and not t for p, t in rows)
    return {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "accuracy": round((tp + tn) / len(rows), 3) if rows else None}


def main():
    compare, single, failed, errors, drift = [], [], 0, [], []
    backends = set()
    for folder in sys.argv[1:]:
        run = json.loads((Path(folder) / "run.json").read_text())
        backends.add(run.get("vlm"))
        if run.get("true_final_pose"):
            errors.append(math.hypot(*run["true_final_pose"][:2]))
        if run.get("final_odom_pose"):
            drift.append(math.hypot(*run["final_odom_pose"][:2]))
        for sid, st in run["stations"].items():
            truth = run["truth"][sid] != "none"
            for key, rows in (("compare", compare), ("single", single)):
                r = st.get(key)
                if r is None:
                    continue
                if "changed" in r:
                    rows.append((r["changed"], truth))
                else:
                    failed += 1
    print(json.dumps({
        "vlm_backends": sorted(str(b) for b in backends),
        "before_after": score(compare), "single_frame": score(single), "vlm_failures": failed,
        "true_return_error_m": [round(e, 3) for e in errors], "odom_return_error_m": [round(e, 3) for e in drift],
    }, indent=2))


if __name__ == "__main__":
    main()
