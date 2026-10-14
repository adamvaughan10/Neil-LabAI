"""
Turn synced recordings (logs/session_*, from gamepad_drive.py --record) into episode
folders for the SmolVLA pipeline (vla-learning/smolvla-pipeline, DATA-CONTRACT.md):

    episodes/ep_0000/  episode.json  frames.jsonl  front.mp4  top.mp4

    python scripts/session_to_episode.py logs/session_* --out episodes
        -> episodes/target/ep_0000 ...  and  episodes/buttons/ep_0000 ...   (two datasets, default)
    python scripts/session_to_episode.py logs/session_* --out episodes_hat --action hat --task "pick up the cup"
        -> episodes_hat/ep_0000 ...   (one --action: no sub-folder)

Then check_episodes.py and convert_to_lerobot.py from the pipeline take it from there.

--action picks what goes in "action" (one dataset per choice; the same frames, state and
videos in each), all in robot terms (+ = forward /
arm down / gripper open, the mounting sign flips applied):
    target  the controller's target: wheel speeds, arm and gripper target angles (degrees)
    hat     the Build HAT calls the Pi made: the wheel speeds the HAT was running (after the
            reverse delay), and the degrees of every run_for_degrees issued during that frame
            for the arm and gripper (0 when none)
    buttons which gamepad buttons were pressed, as a 6-number vector
            [dpad_x, dpad_y, X, A, B, Y]: dpad_x left -1 / right +1, dpad_y up +1 / down -1,
            buttons 1 if pressed at any moment during the frame, else 0. The action keys are
            then dpad_x, dpad_y, x, a, b, y: set the pipeline's neil_features.ACTION_FIELDS
            to BUTTON_FIELDS below before check_episodes.py / convert_to_lerobot.py.
All three are kept in every line anyway, as "target", "hat" and "buttons", so any of them
can be trained on later.

state is the measured motors: wheel speeds, arm and gripper encoder angles (robot terms).
Sessions recorded at the pipeline's 10 fps (gamepad_drive.py --record's default) become
one frame per step. Sessions at another rate are resampled: each frame takes the nearest
recorded step (button presses and arm/gripper degrees from skipped steps are added to it).
From 15 fps that gives frames alternately 67 and 133 ms apart, so record at 10 fps.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config  # noqa: E402

SIGN = {"left_wheel": config.LEFT_WHEEL_SIGN_FORWARD, "right_wheel": config.RIGHT_WHEEL_SIGN_FORWARD,
        "arm": config.ARM_MOTOR_SIGN_DOWN, "gripper": config.GRIPPER_MOTOR_SIGN_OPEN}
CAMERAS = {"front": "pi", "top": "external"}  # pipeline name -> recorder camera
BUTTON_FIELDS = ["dpad_x", "dpad_y", "x", "a", "b", "y"]  # action keys with --action buttons
TASK = "pick up the cup"  # must match neil_features.TASK in the pipeline


def robot(role: str, v):
    return None if v is None else SIGN[role] * v


def frame_rows(steps: list[dict], fps: float) -> list[tuple[dict, list[dict]]]:
    """(chosen step, steps it stands for) for each output frame at fps."""
    if len(steps) > 1 and abs((len(steps) - 1) / (steps[-1]["t"] - steps[0]["t"]) - fps) < 0.05 * fps:
        return [(s, [s]) for s in steps]  # recorded at fps already: one frame per step
    t0, t1 = steps[0]["t"], steps[-1]["t"]
    times = [t0 + k / fps for k in range(int((t1 - t0) * fps) + 1)]
    ts = np.array([s["t"] for s in steps])
    picked = [int(np.abs(ts - t).argmin()) for t in times]
    spans = [steps[(picked[i - 1] + 1 if i else 0):picked[i] + 1] for i in range(len(picked))]
    return [(steps[p], span) for p, span in zip(picked, spans)]


def convert(session: Path, out: Path, action: str, task: str, success: bool, fps: float) -> Path:
    info = json.loads((session / "info.json").read_text())
    steps = [json.loads(line) for line in (session / "steps.jsonl").read_text().splitlines() if line.strip()]
    steps = [s for s in steps if s.get("motors") and s.get("action") and all(s.get(c) for c in CAMERAS.values())]
    if abs(info["fps"] - fps) > 0.05 * fps:
        print(f"  {session.name} was recorded at {info['fps']:g} fps: resampling to {fps:g} gives uneven frame "
              f"spacing; record at {fps:g} fps (gamepad_drive.py --record's default) instead")
    if not steps:
        raise ValueError("no step has motors, action and both cameras (recorded with gamepad_drive.py --record?)")
    out.mkdir(parents=True, exist_ok=True)
    taken = [int(p.name[3:]) for p in out.glob("ep_*") if p.name[3:].isdigit()]
    folder = out / f"ep_{max(taken, default=-1) + 1:04d}"
    folder.mkdir()

    lines, writers = [], {}
    try:
        for i, (step, span) in enumerate(frame_rows(steps, fps)):
            m, a, h = step["motors"], step["action"], step.get("hat_commands")
            state = {"left_speed": robot("left_wheel", m["left_wheel"]["speed"]),
                     "right_speed": robot("right_wheel", m["right_wheel"]["speed"]),
                     "arm_pos": robot("arm", m["arm"]["pos_deg"]),
                     "grip_pos": robot("gripper", m["gripper"]["pos_deg"])}
            target = {"left": robot("left_wheel", a["left_wheel"]["speed"]),
                      "right": robot("right_wheel", a["right_wheel"]["speed"]),
                      "arm": robot("arm", a["arm"]["pos_deg"]), "grip": robot("gripper", a["gripper"]["pos_deg"])}
            hat = {"left": robot("left_wheel", h["left_wheel"]["speed"]) if h else 0,
                   "right": robot("right_wheel", h["right_wheel"]["speed"]) if h else 0,
                   "arm": robot("arm", sum((s.get("hat_commands") or {}).get("arm", {}).get("degrees") or 0
                                           for s in span)),
                   "grip": robot("gripper", sum((s.get("hat_commands") or {}).get("gripper", {}).get("degrees") or 0
                                                for s in span))}
            # Buttons over the steps this frame stands for, so a press between two frames isn't
            # lost: X/A/B/Y are 1 if pressed in any of them; the D-pad takes the latest direction
            # held (both axes together).
            vectors = [s["gamepad"]["vector"] for s in span if s.get("gamepad")]
            buttons = None
            if vectors:
                dpad = next((v[:2] for v in reversed(vectors) if any(v[:2])), [0, 0])
                buttons = dict(zip(BUTTON_FIELDS, dpad + [max(v[k] for v in vectors) for k in range(2, 6)]))
            elif action == "buttons":
                raise ValueError("no gamepad data: recorded before buttons were saved")
            chosen = {"target": target, "hat": hat, "buttons": buttons}[action]
            lines.append({"i": i, "t": step["t"], "state": state, "action": chosen,
                          "target": target, "hat": hat, "buttons": buttons, "step": step["step"]})
            for name, cam in CAMERAS.items():
                img = cv2.imdecode(np.frombuffer((session / step[cam]["file"]).read_bytes(), np.uint8),
                                   cv2.IMREAD_COLOR)
                rot = info["cameras"][cam]["rotation"]
                img = {90: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), 180: cv2.rotate(img, cv2.ROTATE_180),
                       270: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)}.get(rot, img)
                if name not in writers:
                    size = (img.shape[1], img.shape[0])
                    w = cv2.VideoWriter(str(folder / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"avc1"), fps, size)
                    if not w.isOpened():  # this OpenCV build has no H.264
                        w = cv2.VideoWriter(str(folder / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
                    writers[name] = (w, size)
                w, size = writers[name]
                w.write(img if (img.shape[1], img.shape[0]) == size else cv2.resize(img, size))
    finally:
        for w, _ in writers.values():
            w.release()

    (folder / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines))
    (folder / "episode.json").write_text(json.dumps({
        "task": task, "success": success, "frames": len(lines),
        "date": time.strftime("%Y-%m-%d", time.localtime(steps[0]["t"])),
        "source": session.name, "action": action, "fps": fps,
        "action_fields": BUTTON_FIELDS if action == "buttons" else ["left", "right", "arm", "grip"],
        "units": {"state": "wheel speed -100..100 (+ forward), arm/gripper encoder degrees (+ down / + open)",
                  "target": "controller target: wheel speeds; arm/gripper target angles, degrees",
                  "hat": "Build HAT calls: wheel speeds running; arm/gripper run_for_degrees degrees this frame",
                  "buttons": "[dpad_x, dpad_y, X, A, B, Y]: -1/0/1 D-pad (+ right / + up), 1 = pressed this frame"},
    }, indent=2) + "\n")
    return folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", type=Path, nargs="+", help="logs/session_* folders")
    ap.add_argument("--out", type=Path, default=Path("episodes"))
    ap.add_argument("--action", choices=("target", "hat", "buttons"), nargs="+", default=["target", "buttons"],
                    help="one dataset per choice (default: target and buttons)")
    ap.add_argument("--task", default=TASK, help="the instruction sentence, the same in every episode")
    ap.add_argument("--failed", action="store_true", help="mark these episodes success=false")
    ap.add_argument("--fps", type=float, default=10, help="the pipeline's frame rate")
    args = ap.parse_args()
    for action in args.action:
        out = args.out / action if len(args.action) > 1 else args.out
        for session in args.sessions:
            try:
                folder = convert(session, out, action, args.task, not args.failed, args.fps)
                print(f"{session.name} -> {folder}")
            except (OSError, ValueError, KeyError) as exc:
                print(f"{session.name}: skipped for {action} ({exc})")
        fields = BUTTON_FIELDS if action == "buttons" else ["left", "right", "arm", "grip"]
        print(f"{out}: train with neil_features.ACTION_FIELDS = {fields}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
