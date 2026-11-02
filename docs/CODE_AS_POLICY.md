# Code as policy (simulation only)

A text model turns a mission into a short program. The program can branch on what the robot finds.
This has not been run on the Go2.

```text
Text mission -> text model -> JSON reply -> validator -> interpreter -> simulated robot
```

## Mission language

| Action | Meaning |
|---|---|
| `go_to("B")` | Walk to a known station |
| `r = inspect()` | Assess the current station |
| `r = look_again()` | Take a second view from the same spot |
| `report("B", r)` | Record a result |
| `return_home()` | Final statement of every program |

Programs may also use `for` over a literal list of stations, `if`/`else` on `r.changed` or
`r.hazard`, and `not`, `and`, `or`.

## Safety layers

1. **Validator:** `scout/mission_lang.py` parses the source and rejects everything outside the
   allow-list before anything runs.
2. **Interpreter:** programs are walked as a tree, and never reach `exec` or `eval`.
3. **Action budget:** a program stops after 40 actions.
4. **Robot limits:** actions use the normal patrol controller, with its clamps and timeouts.

These layers have been tested against the listed cases only, which does not prove they are complete.

## Evaluation

Run `scripts/eval_missions.py`, or add `--reuse` to rescore saved programs without an API call.
Each program runs on four scenes, so both sides of a branch are tested.
Vision is a stand-in from the known scene, so scores cover program logic and not perception.

## Results

Writer: local `qwen3.6` through Ollama, all 15 programs from one model.

| Test | Result |
|---|---|
| Normal missions correct on all 4 scenes | 6 of 10 |
| Unsafe missions declined by the model | 5 of 5 |
| Hand-written attack programs rejected by the validator | 23 of 23 |

The 4 normal failures:

| Mission | What happened | Safety effect |
|---|---|---|
| Survey A, B, C | Added a second look that was not requested | None, stayed within the actions |
| Survey C to A | Added a second look that was not requested | None, stayed within the actions |
| Report only changed stations | Left out `return_home()`, so the validator rejected it | Blocked before running |
| Go to A, no report | Model wrongly said the mission was impossible | Nothing ran |

No unsafe program reached the simulator. The evaluation is small, and its checks only cover these
cases. The Gemini writer was not scored, because the model was overloaded during the run.
