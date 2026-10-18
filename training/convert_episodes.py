"""Turn episode folders from the team's recorder into one LeRobot dataset.

    python convert_episodes.py --name test_1 ../Test_1
    python convert_episodes.py --name pick_cup ../episodes/*      (many episodes at once)

Each episode folder has info.json (fps), steps.jsonl (one line per frame) and the
images pi/NNNNNN.jpg and external/NNNNNN.jpg. The MP4 files are not used.

From each line of steps.jsonl we keep:
    action = action.vector: left wheel speed, right wheel speed, arm target angle,
             gripper target angle (what the controller asked for)
    state  = the same 4 values as measured by the motors, in the same signs as the
             action: left wheel and arm and gripper are mounted reversed, so their
             motor readings are flipped (-1)
If a recording has no "action" field, the action falls back to the motor speeds at
the next frame. Quiet frames at the start and end are cut, keeping 1 second.

Recordings whose action names say "left_wheel.pos" (the controller that moves the
wheels with run_for_degrees, from 2026-10-14 evening) are converted differently:
    action wheels = degrees each wheel still has to turn: the wheel's target angle
                    minus its current angle, wrapped to -180..180 (+ = forward)
    arm, gripper  = pos_deg moves its zero when the Pi or recorder restarts, but
                    abs_pos_deg does not. So state and targets are put on one fixed
                    zero: arm = abs - 14, gripper = abs + 93 (the zero of the first
                    sessions), then flipped like above.
"""
import argparse
import copy
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from neil_io import FEATURES, IMG_H, IMG_W, TOP_H, TOP_W

ACTION_NAMES = ["left_wheel.vel", "right_wheel.vel", "arm.pos", "grip.pos"]
ANGLE_ACTION_NAMES = ["left_wheel.deg_to_go", "right_wheel.deg_to_go", "arm.pos", "grip.pos"]
ARM_ZERO, GRIP_ZERO = 14, -93  # abs_pos_deg - pos_deg in the first sessions
STATE_SIGN = np.array([-1, 1, -1, -1], dtype=np.float32)  # motor reading -> action signs


def load_rgb(path, w, h):
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)


def wrap(deg):
    return (deg + 180) % 360 - 180


def angle_episode_arrays(rows):
    """For recordings with wheel angle actions: see the module docstring."""
    m = [r["motors"] for r in rows]
    arm_abs = np.array([x["arm"]["abs_pos_deg"] for x in m], dtype=np.float32)
    grip_abs = np.array([x["gripper"]["abs_pos_deg"] for x in m], dtype=np.float32)
    state = np.stack([-np.array([x["left_wheel"]["speed"] for x in m]),
                      np.array([x["right_wheel"]["speed"] for x in m]),
                      -(arm_abs - ARM_ZERO), -(grip_abs - GRIP_ZERO)], 1).astype(np.float32)
    vec = np.array([r["action"]["vector"] for r in rows], dtype=np.float32)
    # The wheel targets use the same signs as -pos_deg (left) and pos_deg (right).
    left_now = wrap(-np.array([x["left_wheel"]["pos_deg"] for x in m], dtype=np.float32))
    right_now = wrap(np.array([x["right_wheel"]["pos_deg"] for x in m], dtype=np.float32))
    # The arm and gripper targets use this session's zero; move them to the fixed one.
    arm_shift = np.median([x["arm"]["abs_pos_deg"] - x["arm"]["pos_deg"] for x in m]) - ARM_ZERO
    grip_shift = np.median([x["gripper"]["abs_pos_deg"] - x["gripper"]["pos_deg"] for x in m]) - GRIP_ZERO
    action = np.stack([wrap(vec[:, 0] - left_now), wrap(vec[:, 1] - right_now),
                       vec[:, 2] - arm_shift, vec[:, 3] - grip_shift], 1).astype(np.float32)
    return state, action


def episode_arrays(rows):
    if rows[0].get("action") and rows[0]["action"].get("names", [""])[0] == "left_wheel.pos":
        return angle_episode_arrays(rows)
    m = [r["motors"] for r in rows]
    state = np.array([[x["left_wheel"]["speed"], x["right_wheel"]["speed"],
                       x["arm"]["pos_deg"], x["gripper"]["pos_deg"]] for x in m], dtype=np.float32) * STATE_SIGN
    if all(r.get("action") for r in rows):
        action = np.array([r["action"]["vector"] for r in rows], dtype=np.float32)
    else:
        speeds = np.array([[x[k]["speed"] for k in ("left_wheel", "right_wheel", "arm", "gripper")] for x in m],
                          dtype=np.float32)
        action = np.vstack([speeds[1:], speeds[-1:]])
    return state, action


def active_range(rows, state, action, margin):
    """First and last frame where something moves or a button is pressed, plus a margin."""
    busy = np.abs(state[:, :2]).sum(1) > 0
    busy |= np.r_[False, (np.abs(np.diff(action, axis=0)).sum(1) > 0)]
    busy |= np.r_[False, (np.abs(np.diff(state[:, 2:], axis=0)).sum(1) > 1)]
    busy |= np.array([any(r.get("gamepad", {}).get("vector") or [0]) for r in rows])
    idx = np.flatnonzero(busy)
    if len(idx) == 0:
        return 0, len(rows)
    return max(0, idx[0] - margin), min(len(rows), idx[-1] + margin + 1)


def convert_episode(ep_dir, ds, task, fps, trim):
    rows = [json.loads(line) for line in open(ep_dir / "steps.jsonl")]
    rows = [r for r in rows if r.get("motors") and r.get("action")]  # the first frame can arrive early
    state, action = episode_arrays(rows)
    a, b = active_range(rows, state, action, fps) if trim else (0, len(rows))
    for r, s, act in zip(rows[a:b], state[a:b], action[a:b]):
        ds.add_frame({
            "observation.state": s,
            "observation.images.camera1": load_rgb(ep_dir / r["pi"]["file"], IMG_W, IMG_H),
            "observation.images.camera2": load_rgb(ep_dir / r["external"]["file"], TOP_W, TOP_H),
            "action": act,
            "task": task,
        })
    ds.save_episode()
    return len(rows), a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes", nargs="+", help="episode folders (each has info.json and steps.jsonl)")
    ap.add_argument("--name", required=True, help="dataset folder name under data/")
    ap.add_argument("--task", default="pick up the cup")
    ap.add_argument("--no-trim", action="store_true", help="keep the quiet frames at start and end")
    args = ap.parse_args()

    eps = [Path(e) for e in args.episodes]
    rates = {json.load(open(e / "info.json"))["fps"] for e in eps}
    if len(rates) != 1:
        raise SystemExit(f"Episodes have different fps: {rates}. Record all episodes at one rate.")
    fps = int(rates.pop())

    features = copy.deepcopy(FEATURES)
    names = {tuple(json.loads(open(e / "steps.jsonl").readline()).get("action", {}).get("names", ACTION_NAMES))
             for e in eps}
    if len(names) != 1:
        raise SystemExit(f"Episodes save different actions: {names}. Convert them separately.")
    names = list(names.pop())  # as the recorder saved them
    features["action"]["names"] = ANGLE_ACTION_NAMES if names[0] == "left_wheel.pos" else names
    features["observation.state"]["names"] = ACTION_NAMES

    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    root = Path("data") / args.name
    if root.exists():
        shutil.rmtree(root)
    ds = LeRobotDataset.create(f"local/{args.name}", fps=fps, features=features, root=root, robot_type="neil")
    for ep in eps:
        n, a, b = convert_episode(ep, ds, args.task, fps, not args.no_trim)
        print(f"Converted {ep}: kept frames {a} to {b - 1} of {n} ({(b - a) / fps:.1f} s)")
    ds.finalize()
    print("Dataset folder:", ds.root, "episodes:", ds.num_episodes, "fps:", fps)


if __name__ == "__main__":
    main()
