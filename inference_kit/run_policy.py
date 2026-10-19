"""Let a trained SmolVLA drive Neil.

    python run_policy.py --model model                                                   # v1: wheel speeds
    python run_policy.py --model ../models/handoff_pick_cup_pos2/pretrained_model --action-mode delta
    python run_policy.py --model ../models/pick_cup_angle_182076/pretrained_model --action-mode angle
    python run_policy.py --model ... --action-mode delta --replay runs/run_20261014_142049   # no robot

--action-mode picks how the model's 4 numbers are read (each model's README says which):
  v1     inference_kit/model (job 181436): state and action are wheel speeds plus arm and
         gripper angles (pos_deg). Each action is a wheel speed and two target angles.
  delta  models/handoff_pick_cup_pos2: the state's arm and gripper come from abs_pos_deg,
         and each wheel action is the degrees it should still turn from where it is now
         (target - measured, wrapped to -180..180 in training). Moves under --deadband
         degrees count as 0, and every value is clipped to the model's training range.
  angle  models/pick_cup_angle_182076 (no README; read from its normaliser stats): the arm
         and gripper are -abs_pos_deg, each wheel's state is its angle since the start of the
         run, and each wheel action is a target angle on that scale. The wheel turns by
         target - measured (at most 120 degrees per command), as in delta mode.
--replay plays a recorded run (images and motor readings) instead of Neil: nothing moves,
and the commands Neil would get are printed and saved in runs/dryrun_*.

The model runs on this laptop (Apple GPU "mps", NVIDIA "cuda", or "cpu"). Every --replan
actions it plans again, which can take 1 to 2 s on a small laptop; the wheels stop
during that pause. Press Ctrl+C to stop the robot at any time.
The delta mode needs the pi_bridge.py next to this file on the Pi (it adds wheel-degree
and abs-angle commands; v1 commands work as before).
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

import torch

from neil_io import ABS0, FPS, Bridge, delta_command, open_cameras, state_vector


# Typical start pose in the recorded demos (recorder signs): arm low, gripper open.
# The delta model's demos start with the gripper a little less open (state about -22 to -24;
# under 1% of its frames are above -22).
# The angle model's scale puts that same pose at arm -12, gripper 70.
START = {"v1": (2.0, -15.0), "delta": (2.0, -23.0), "angle": (-12.0, 70.0)}


def start_command(mode):
    arm, grip = START[mode]
    if mode in ABS0:
        za, zg = ABS0[mode]
        return {"left": 0, "right": 0, "arm_abs": za - arm, "grip_abs": zg - grip}
    return {"left": 0, "right": 0, "arm_pos": arm, "grip_pos": grip}


def warm_up(bridge, mode, timeout=5.0, steady=5, tol=1.0):
    """Move to the start pose and wait until 5 readings in a row change by less than 1 degree."""
    last, count, t_end = None, 0, time.time() + timeout
    while time.time() < t_end:
        s = state_vector(bridge.command(start_command(mode)), mode)[2:]
        count = count + 1 if last is not None and np.abs(s - last).max() < tol else 0
        last = s
        if count >= steady:
            return s
        time.sleep(0.1)
    print("Warning: motor readings did not settle in", timeout, "s; starting anyway")
    return last


def settle(bridge, seconds):
    """Hold still (wheels stopped, arm and gripper at their targets) and return the last state."""
    state = bridge.hold()
    for _ in range(max(1, round(seconds * 10))):
        time.sleep(0.1)
        state = bridge.hold()
    return state


def action_range(model_dir):
    """The training range (min, max) of each action value, from the model's normaliser."""
    from safetensors.torch import load_file
    stats = load_file(str(Path(model_dir) / "policy_postprocessor_step_0_unnormalizer_processor.safetensors"))
    return stats["action.min"].numpy(), stats["action.max"].numpy()


class Replay:
    """A recorded run (runs/run_*: front/, top/, steps.jsonl) stands in for Neil and both cameras.
    Each command moves on to the next recorded frame; nothing is sent anywhere."""

    def __init__(self, run_dir):
        self.dir = Path(run_dir)
        self.rows = [json.loads(line) for line in open(self.dir / "steps.jsonl")]
        self.i = 0
        self.done = False
        self.wheels = [0.0, 0.0]  # the recording has no wheel angles: assume each move happens as sent

    def state(self):
        left, right, arm, grip = self.rows[self.i]["state"]
        # The kit runs were recorded before 16:10, when abs_pos_deg - pos_deg was +14 (arm) and
        # -93 (gripper), raw motor signs; so the delta state equals the recorded one.
        (za, zg) = ABS0["delta"]
        return {"left_speed": left, "right_speed": right, "arm_pos": arm, "grip_pos": grip,
                "arm_abs": za - arm, "grip_abs": zg - grip, "left_deg": self.wheels[0], "right_deg": self.wheels[1]}

    def image(self, name):
        img = cv2.imread(str(self.dir / name / f"{self.rows[self.i]['i']:06d}.jpg"))
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def command(self, cmd):
        if isinstance(cmd, dict):
            self.wheels = [w + (cmd.get(k) or 0) for w, k in zip(self.wheels, ("left_deg", "right_deg"))]
        if self.i + 1 >= len(self.rows):
            self.done = True
        else:
            self.i += 1
        return self.state()

    def send(self, action):
        return self.command(action)

    def hold(self):
        return self.state()

    def stop(self):
        pass


class ReplayCamera:
    def __init__(self, replay, name):
        self.replay, self.name = replay, name

    def read(self):
        return self.replay.image(self.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", "--policy", dest="policy", required=True,
                    help="folder of the trained model (pretrained_model/ from Athena)")
    ap.add_argument("--action-mode", choices=["v1", "delta", "angle"], default="v1",
                    help="v1 = wheel speeds (inference_kit/model); delta = wheel degrees to go (handoff_pick_cup_pos2); "
                         "angle = wheel target angles (pick_cup_angle_182076)")
    ap.add_argument("--task", default="pick up the cup", help="the same task sentence as in the recording")
    default_device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    ap.add_argument("--device", default=default_device)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--replan", type=int, default=10, help="plan again after this many actions (10 = every 1 s, max 50)")
    ap.add_argument("--pause", type=float, default=0,
                    help="after each plan's actions, stop the wheels and wait this many seconds, so the next plan sees a settled robot")
    ap.add_argument("--ramp", type=float, default=0,
                    help="v1 only: most a wheel speed may change per step (3 = 0 to 30 over 1 s); 0 = send the model's speeds as they are")
    ap.add_argument("--smooth", type=int, default=1,
                    help="v1 only: drive the wheels toward the average of the model's last N wheel speeds (1 = no averaging)")
    ap.add_argument("--deadband", type=float, default=3.0,
                    help="delta and angle: wheel moves under this many degrees count as 0")
    ap.add_argument("--replay", metavar="RUN_DIR",
                    help="dry run: play a recorded run (e.g. runs/run_20261014_142049) instead of Neil; nothing moves")
    ap.add_argument("--no-record", action="store_true", help="don't save the run in runs/")
    args = ap.parse_args()
    delta = args.action_mode in ("delta", "angle")  # both send wheel moves in degrees

    # Refuse a model / mode mismatch: v1 wheel actions are speeds within +-30, delta ones
    # are degrees to go (about +-100), angle ones are target angles (up to about 650).
    lo, hi = action_range(args.policy)
    wheel_max = float(np.abs(np.concatenate([lo[:2], hi[:2]])).max())
    want = "v1" if wheel_max <= 40 else "delta" if wheel_max <= 150 else "angle"
    if want != args.action_mode:
        raise SystemExit(f"This model's wheel actions reach {wheel_max:g} in training, which fits "
                         f"--action-mode {want}, not {args.action_mode}.")
    print(f"Action mode {args.action_mode}; training range (left, right, arm, grip): "
          f"min {lo.round(1).tolist()} max {hi.round(1).tolist()}")

    from lerobot.common.control_utils import predict_action
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    device = torch.device(args.device)
    policy = SmolVLAPolicy.from_pretrained(args.policy).to(device).eval()
    args.replan = max(1, min(args.replan, policy.config.chunk_size))
    policy.config.n_action_steps = args.replan  # read by policy.reset() below
    pre, post = make_pre_post_processors(policy.config, pretrained_path=args.policy,
                                         preprocessor_overrides={"device_processor": {"device": args.device}})
    policy.reset()

    if args.replay:
        bridge = Replay(args.replay)
        front, top = ReplayCamera(bridge, "front"), ReplayCamera(bridge, "top")
        state = bridge.hold()
        print("Dry run on", args.replay, f"({len(bridge.rows)} frames): nothing is sent to Neil")
    else:
        bridge = Bridge()
        front, top = open_cameras()
        # The first readings after the bridge starts can be stale (a closed gripper from the
        # last run), and the model must start from an open gripper, like every demo.
        print("Warm-up: opening the gripper and setting the arm to the start pose ...")
        warm_up(bridge, args.action_mode)
        state = bridge.hold()
    wheel0 = (state["left_deg"] or 0.0, state["right_deg"] or 0.0) if args.action_mode == "angle" else (0.0, 0.0)
    print("Start state (left, right, arm, grip):", state_vector(state, args.action_mode, wheel0).tolist())
    out = None
    if not args.no_record:  # every step: both camera images as the model saw them, the state and the action
        out = Path("runs") / time.strftime(("dryrun_" if args.replay else "run_") + "%Y%m%d_%H%M%S")
        (out / "front").mkdir(parents=True)
        (out / "top").mkdir()
        log = open(out / "steps.jsonl", "w")
        (out / "run.json").write_text(json.dumps({"model": str(Path(args.policy).resolve()), **vars(args)}, indent=2))
        print("Recording to", out)
    t_end = time.time() + args.seconds
    i = 0
    wheels, recent = [0.0, 0.0], []  # v1: speeds sent to the wheels; the model's recent wheel speeds
    try:
        while time.time() < t_end and not getattr(bridge, "done", False):
            if args.pause and i and i % args.replan == 0:
                print(f"\nStep {i}: paused {args.pause:g} s before the next plan")
                state = settle(bridge, args.pause)
                wheels, recent = [0.0, 0.0], []  # the wheels stopped during the pause
            t0 = time.time()
            obs = {
                "observation.state": state_vector(state, args.action_mode, wheel0),
                "observation.images.camera1": front.read(),
                "observation.images.camera2": top.read(),
            }
            action = predict_action(obs, policy, device, pre, post, use_amp=False,
                                    task=args.task, robot_type="neil")
            action = action.squeeze(0).cpu().tolist()
            if delta:
                # The model's values as they are (no ramp or smoothing: see the model's README).
                cmd = delta_command(action, lo, hi, args.deadband, args.action_mode,
                                    wheel_now=obs["observation.state"][:2])
                sent = [cmd["left_deg"], cmd["right_deg"], cmd["arm_abs"], cmd["grip_abs"]]
            else:
                recent = (recent + [action[:2]])[-args.smooth:]
                goal = [sum(r[w] for r in recent) / len(recent) for w in (0, 1)]
                ramp = args.ramp or float("inf")
                wheels = [wheels[w] + max(-ramp, min(ramp, goal[w] - wheels[w])) for w in (0, 1)]
                sent = wheels + action[2:]
            if out:
                for name in ("front", "top"):
                    img = obs["observation.images.camera1" if name == "front" else "observation.images.camera2"]
                    cv2.imwrite(str(out / name / f"{i:06d}.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
                row = {"i": i, "t": t0, "state": obs["observation.state"].tolist(),
                       "action": action, "sent": sent, "new_plan": i % args.replan == 0}
                if delta:  # wheel encoder angles (recorder signs) when this step's command went out
                    row["wheel_deg"] = [state.get("left_deg"), state.get("right_deg")]
                log.write(json.dumps(row) + "\n")
            i += 1
            state = bridge.command(cmd) if delta else bridge.send(sent)
            print(" ".join(f"{v:6.1f}" for v in sent), end="\n" if args.replay else "\r")
            if not args.replay:
                time.sleep(max(0.0, 1.0 / FPS - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        if out:
            log.close()
            print(f"\nSaved {i} steps to {out}")


if __name__ == "__main__":
    main()
