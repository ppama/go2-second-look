# Development blog: Second Look

A record of how the design changed, including the ideas that were dropped. All work happened in
the last 24 hours before the deadline, so most decisions are about what to leave out.

## Starting point: a scout with a scan

The first plan was a lunar site survey: a Go2 visits marked stations, a vision language model (VLM)
describes each one, and the robot returns to its start. One decision came early and has not
changed: **the VLM does not steer.** A call takes seconds, while walking needs control at 10 Hz.
Odometry drives, and the VLM speaks only while the robot is stopped.

## Idea 1: use the lab scans as a digital twin

Scans of the lab already existed, so the next idea was to compare live frames with renders of the
scan, and report what changed. A quick render at Go2 camera height killed the plan. Large objects
were recognisable, but there were holes, smears and streaks. A VLM comparing a render with a
photo would mostly report render damage.

## Idea 2: the robot is its own reference

The fix was simple. Run the patrol twice and compare the robot's own frames. Same camera, same
lens, no render, no map alignment. This removed the riskiest part of the project and kept the
interesting question: *what changed since I was last here?*

## One interface, two robots

The patrol talks to a small robot interface with two backends, the Go2 and a MuJoCo stand-in. The
sim moves the body from velocity commands, with slip that odometry cannot see, as on a real robot.
It does not simulate walking, because the sport controller on the Go2 already does that.

The SDK method names were checked against the installed source rather than examples. The wrapper
was then tested against a fake SDK. Those tests check my logic, not the robot.

## What the simulation taught me

With a little drift, pixel difference flagged every unchanged station: 23 false alarms out of 23.
It also showed that odometry can report a 9 cm return while the robot is 30 cm away. So the return
error must be measured with a tape, and the comparison must tolerate viewpoint shift. (Those drift
values are assumptions, so these numbers show a failure mode, not robot performance.)

Gemini handled this much better on the same kind of frames, and a first live test exposed a real
false alarm: drift brought a block into the edge of the frame, and the model reported it as new.
One sentence in the prompt fixed that case.

## Meeting the real API

- The model name in the tutorial no longer existed. The API returned 404, so the project moved to
  the current Robotics ER preview. The patrol logged the failure and finished its route, which
  was a useful accidental test.
- The free tier allows 5 requests per minute and 20 per day. Retrying on a rate limit wastes daily
  quota, so errors are no longer retried, and failed stations can be rerun from saved frames.

## A fallback before the hardware

Hardware is the largest risk, so a complete simulated submission was built first. Every result
in that video is read from logs, and the video states that it is simulation.

## Real2sim: useful, but only for layout

The scans came back as a side result. A converter levels the floor, simplifies the mesh, bakes
colour into a texture, and builds a collision heightfield. Unknown space counts as an obstacle.
The Go2 model rests on that floor, and the same patrol code ran on the best scan. But the scan
quality is too poor for VLM testing, so this is reported as layout testing only.

MuJoCo has no vertex colours, so each face gets one texture pixel. Faces are ordered along a
space-filling curve so that distant mipmaps blend neighbouring surfaces rather than random ones.

A later test changed the verdict on the images. The same bags hold sharp colour frames, and a
Gaussian splat trained on them looks far better than the mesh: 23.8 dB on held-out views. The mesh
failed because it had to commit to a surface. The splat only has to reproduce what a camera saw.

## Bonus 1: code as policy, in simulation only

A fixed patrol cannot say "if the tower fell, look again". So a text model writes a short mission
program. AI-written code is untrusted, which drove the main design choice: **programs never reach
Python's `exec`.** They are parsed into a tree, checked against an allow-list, and run by a small
interpreter whose only actions are the mission actions. There is no way to express a speed or a
coordinate, because the language has no word for them.

Testing used a stand-in for vision that answers from the known scene, so it checks the program's
logic and uses no Robotics ER quota.

The first run stalled when the cloud text model was overloaded. The job now saves after each
mission, times out each request, and resumes. The final run used a local model, which has no rate
limit, so a brief cloud outage no longer stops the work.

## Bonus 2: a detector trained in simulation

Gemini needs a network, and quota is small. A local detector needs neither. A Siamese ResNet18
trains on randomized simulated pairs, including viewpoint jitter, light changes and fake tracks.
It stays offline and never controls the robot. The honest question is whether it transfers.

## Fixing the stop, and breaking everything on purpose

The rehearsal showed drift as the main weakness, so the robot now compares its view with the
reference and corrects its stop. The first version barely helped: plain simulated surfaces gave
the matcher almost nothing to hold. Testing on real sandbox frames, with SLAM as ground truth,
showed the method itself worked, so the sim scene was the harder case.

Tuning then exposed a second problem. At high drift, a wrong match made the robot turn further
off target. A correction you cannot trust is worse than none, so weak matches now cause no move.
I stopped tuning there, to avoid fitting the numbers to one scene. The honest result is that the
guarded version barely changes anything, so it stays off for the real run. The real-frame heading
test is still a promising starting point for later work.

Fault injection paid for itself on its first run, by finding that stops between legs did not retry.

## Results

Results so far, from simulation:

- **Code as policy:** the local model got 6 of 10 normal missions fully right. All 5 unsafe requests
  were declined, and all 23 hand-written attacks were rejected. A program that forgot
  `return_home()` was stopped by the validator, which is the layer doing its job. My first scoring
  also failed a correct program, because my return check was tighter than the controller's own
  tolerance. I loosened the check to 1.5 times that tolerance and recorded why.
- **Detector:** 87.3% on simulated pairs, but 7 of 12 on stations from the site scene, with 5 false
  alarms and no misses. Training on randomized scenes helped, but it did not match Gemini, which
  was right on all 12. Real frames are still untested.
- **Local vision model:** `qwen3.6` wrote programs well, but got its single image test wrong, so
  vision stays with Gemini.

- **Rehearsal:** 48 simulated patrols all completed. Odometry always reported under 10 cm, while true
  return error reached 33 cm at base drift. So the report must use a tape. See `docs/SIM_REHEARSAL.md`.
- **Quota lesson:** I misread when the daily limit resets, and the last rehearsal call hit it.

[Fill in hardware results.]

## What I would do differently

[Fill in after the hardware runs.]

## The local VLM that scored well for the wrong reason

Local qwen3.6 caught 12 of 12 changes with two input images. Splitting false alarms by station showed
it mostly answered by station, and known-answer pairs came back 7 of 12. One side-by-side picture fixed
the controls (12 of 12) on the same frames. Lesson: run controls before trusting a catch rate. Details: docs/VLM_EVAL.md.

Then we warped each frame onto its reference and doubled the resolution. Tuning runs looked strong, but
the held-out runs showed only a modest gain at large drift and none at base. The held-out number is the one reported.
