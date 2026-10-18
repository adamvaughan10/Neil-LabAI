"""Let a trained SmolVLA drive Neil.

    python run_policy.py --policy models/pick_cup_181436/pretrained_model

The model runs on this laptop (Apple GPU "mps", NVIDIA "cuda", or "cpu"). Every 50
frames it plans the next 50 commands, which can take 1 to 2 s on a small laptop;
the wheels stop during that pause. Press Ctrl+C to stop the robot at any time.
A video of the run, for people to watch, goes to runs/run_<date>_<time>/ at 30 frames
per second (--video-fps); the model itself still runs at FPS (10).
NOT YET TESTED ON NEIL.
"""
import argparse
import time
from pathlib import Path

import torch

from neil_io import FPS, Bridge, open_cameras, state_vector
from run_video import RUN_VIDEO_FPS, RunVideo

RUNS = Path(__file__).resolve().parent / "runs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, help="folder of the trained model (copied from Athena)")
    ap.add_argument("--task", default="pick up the cup", help="the same task sentence as in the recording")
    default_device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    ap.add_argument("--device", default=default_device)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--video-fps", type=float, default=RUN_VIDEO_FPS,
                    help=f"frames per second of the video of the run, to watch (default {RUN_VIDEO_FPS}; 0: no video)")
    args = ap.parse_args()

    from lerobot.common.control_utils import predict_action
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    device = torch.device(args.device)
    policy = SmolVLAPolicy.from_pretrained(args.policy).to(device).eval()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=args.policy,
                                         preprocessor_overrides={"device_processor": {"device": args.device}})
    policy.reset()

    bridge = Bridge()
    front, top = open_cameras()
    state = bridge.hold()  # read the start pose without moving
    print("Start state (left, right, arm, grip):", state_vector(state).tolist())
    t_end = time.time() + args.seconds
    video = None
    try:
        if args.video_fps:
            video = RunVideo({"front": front, "top": top}, RUNS / time.strftime("run_%Y%m%d_%H%M%S"),
                             args.video_fps).start()
        while time.time() < t_end:
            t0 = time.time()
            obs = {
                "observation.state": state_vector(state),
                "observation.images.camera1": front.read(),
                "observation.images.camera2": top.read(),
            }
            action = predict_action(obs, policy, device, pre, post, use_amp=False,
                                    task=args.task, robot_type="neil")
            action = action.squeeze(0).cpu().tolist()
            state = bridge.send(action)
            print(" ".join(f"{v:6.1f}" for v in action), end="\r")
            time.sleep(max(0.0, 1.0 / FPS - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            bridge.stop()  # the robot first
        finally:
            if video:
                video.stop()
                print(f"\nVideo of the run: {video.out_dir / 'side_by_side.mp4'}")


if __name__ == "__main__":
    main()
