"""Visual re-alignment: match the live view to the reference frame and correct the stop.

It corrects heading and distance to the scene. Sideways error is not corrected, because a
sideways move needs a second motion axis and a known scene depth.
"""
import math

import cv2
import numpy as np

from scout.patrol import face, stop_robot
from scout.robot import wrap

RATIO, MIN_INLIERS = 0.8, 8


def estimate(before, after, fx):
    """Return the heading error and scale change of after relative to before, or None."""
    a = cv2.cvtColor(before, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(after, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(4000, contrastThreshold=0.02)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return None
    pairs = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
    if len(good) < MIN_INLIERS:
        return None
    pa = np.float32([ka[m.queryIdx].pt for m in good])
    pb = np.float32([kb[m.trainIdx].pt for m in good])
    matrix, mask = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if matrix is None or int(mask.sum()) < MIN_INLIERS:
        return None
    h, w = a.shape
    centre = matrix @ np.array([w / 2, h / 2, 1.0])
    return {"yaw": math.atan2(centre[0] - w / 2, fx), "scale": float(np.hypot(matrix[0, 0], matrix[1, 0])), "inliers": int(mask.sum())}


def overlap(before, after, min_inliers=MIN_INLIERS, min_shared=0.5):
    """Warp after onto before and grey out what both cannot see. None if no trusted match.

    Only an image is changed, so a wrong match costs one wrong report, never a wrong motion.
    """
    a = cv2.cvtColor(before, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(after, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(4000, contrastThreshold=0.02)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 2 or len(kb) < 2:
        return None
    pairs = cv2.BFMatcher().knnMatch(db, da, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
    if len(good) < min_inliers:
        return None
    pb = np.float32([kb[m.queryIdx].pt for m in good])
    pa = np.float32([ka[m.trainIdx].pt for m in good])
    matrix, mask = cv2.estimateAffinePartial2D(pb, pa, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if matrix is None or int(mask.sum()) < min_inliers:
        return None
    h, w = a.shape
    warped = cv2.warpAffine(after, matrix, (w, h))
    seen = cv2.warpAffine(np.full((h, w), 255, np.uint8), matrix, (w, h))
    seen = cv2.erode(seen, np.ones((15, 15), np.uint8)) > 0
    if seen.mean() < min_shared:
        return None
    left, right = before.copy(), warped
    left[~seen] = right[~seen] = 128
    return left, right


def step(robot, cfg, guard, log, distance):
    """A short straight move, measured by odometry."""
    speed = math.copysign(cfg["align"]["speed"], distance)
    dt = cfg["limits"]["control_dt_s"]
    x0, y0, _ = robot.pose()
    start = robot.now()
    while True:
        guard.tick(start)
        x, y, yaw = robot.pose()
        if math.hypot(x - x0, y - y0) >= abs(distance):
            break
        robot.command(speed, 0.0, 0.0)
        log.odom(robot.now(), x, y, yaw, speed, 0.0)
        robot.sleep(dt)
    stop_robot(robot)


def realign(robot, cfg, guard, log, reference):
    """Up to a few small corrections. No match means no move, and the patrol carries on."""
    settings = cfg["align"]
    fx = cfg["camera"]["fx"]
    corrections = []
    for _ in range(settings["iterations"]):
        result = estimate(reference, robot.frame(), fx)
        if result is None:
            corrections.append({"matched": False})
            break
        corrections.append({"matched": True, **{k: round(v, 3) for k, v in result.items()}})
        # A weak match or a large correction is more likely a wrong match, so make no move.
        if result["inliers"] < settings["min_inliers"] or abs(result["yaw"]) > settings["max_turn"] or abs(result["scale"] - 1) > settings["max_scale_change"]:
            corrections[-1]["rejected"] = True
            break
        turn = -result["yaw"]
        # Larger than the reference means too close, so the move is backward.
        move = float(np.clip((1 - result["scale"]) * settings["view_distance"], -settings["max_step"], settings["max_step"]))
        if abs(turn) < settings["yaw_tol"] and abs(move) < settings["move_tol"]:
            break
        if abs(turn) >= settings["yaw_tol"]:
            face(robot, cfg, guard, log, wrap(robot.pose()[2] + turn))
        if abs(move) >= settings["move_tol"]:
            step(robot, cfg, guard, log, move)
        robot.sleep(cfg["control"]["settle_s"])
    return corrections
