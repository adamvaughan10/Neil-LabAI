"""Check a trained model on this laptop, without the robot.

    python check_model.py --policy models/pick_cup_181436/pretrained_model

It feeds recorded frames from data/pick_cup to the model and prints, for each
frame, the recorded action and the model's action side by side, plus the time
the model needs. Use it to check that the laptop is fast enough before driving Neil.
"""
import argparse
import time

import numpy as np
import torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, help="folder of the trained model")
    ap.add_argument("--data", default="pick_cup", help="dataset folder under data/")
    ap.add_argument("--task", default="pick up the cup")
    ap.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    ap.add_argument("--frames", type=int, default=20)
    args = ap.parse_args()

    from lerobot.common.control_utils import predict_action
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    t = time.time()
    policy = SmolVLAPolicy.from_pretrained(args.policy).to(args.device).eval()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=args.policy,
                                         preprocessor_overrides={"device_processor": {"device": args.device}})
    print(f"Model loaded on {args.device} in {time.time() - t:.0f} s")

    ds = LeRobotDataset(f"local/{args.data}", root=f"data/{args.data}", video_backend="pyav")
    policy.reset()
    times, errors = [], []
    print("frame | recorded action          | model action")
    for i in range(args.frames):
        x = ds[i]
        obs = {
            "observation.state": x["observation.state"].numpy(),
            "observation.images.camera1": (x["observation.images.camera1"].permute(1, 2, 0).numpy() * 255).astype(np.uint8),
            "observation.images.camera2": (x["observation.images.camera2"].permute(1, 2, 0).numpy() * 255).astype(np.uint8),
        }
        t = time.time()
        a = predict_action(obs, policy, torch.device(args.device), pre, post, use_amp=False,
                           task=args.task, robot_type="neil").squeeze(0).cpu().numpy()
        times.append(time.time() - t)
        rec = x["action"].numpy()
        errors.append(np.abs(a - rec))
        print(f"{i:5d} | {np.round(rec, 1)} | {np.round(a, 1)}   ({times[-1] * 1000:.0f} ms)")
    times = np.array(times)
    print(f"\nTime per frame: median {np.median(times) * 1000:.0f} ms, slowest {times.max() * 1000:.0f} ms")
    print("Mean difference to the recording (left, right, arm, grip):", np.round(np.mean(errors, 0), 1))
    print("The robot runs at 10 frames per second, so most frames must take under 100 ms.")


if __name__ == "__main__":
    main()
