# Video plan: Second Look (target 2:30, MP4)

All VLM text, boxes and numbers must come from `logs/`. Show that a person changes the scene.

| Time | Shot | On-screen text |
|---|---|---|
| 0:00-0:12 | Close-up of sand, Scout at the edge | Before a crew arrives, the site must be checked again. |
| 0:12-0:25 | Wide shot, labelled stations | Mission: remember the site, find what changed, return. |
| 0:25-0:50 | Patrol 1 at 2x, camera inset | Patrol 1: saving a reference view. Video 2x. |
| 0:50-1:00 | Person topples the tower and removes a block | We change the site by hand. Scout isn't told what changed. |
| 1:00-1:20 | Station A split screen | [logged result] |
| 1:20-1:45 | Station B split screen with box | [logged result] |
| 1:45-2:00 | Station C split screen | [logged result] |
| 2:00-2:15 | Return to start mark, tape measure | Return error: [measured] cm |
| 2:15-2:30 | Survey log, Scout sits | [X/Y] correct. Intended use: repeat site inspection. |

Tools: `make_cards.py` makes split-screen images, `make_survey.py` the final log, `camera_to_mp4.py` the camera inset.
Real run: `make_real_demo.py` builds the video from filmed clips, logs and the tape value.
Fallback: `make_sim_demo.py OUT.mp4 --reference logs/fb_ref --after logs/fb_after` builds a labelled simulation video from logged results.
Shoot order: patrol 1, scene change, patrol 2, return measurement, final log, opening shots.
Check every frame for name plates, screens and people.
