"""
Drive with the gamepad and record training episodes. THIS MOVES THE ROBOT: give it room, keep hands clear of the arm.

Driving is exactly gamepad_drive.py (D-pad drives while held, X/B arm up/down and
Y/A gripper open/close a fixed angle per press). On the keyboard, in this terminal:

    Enter        start an episode / stop it
    s / f / d    after stopping: keep as success / keep as failure / delete it (then Enter)
    Ctrl-C       stop and quit (an unfinished episode is deleted)

Each episode is a folder episodes/ep_NNNN with frames.jsonl, episode.json,
front.mp4 (Pi camera) and top.mp4 (iPhone), as in DATA-CONTRACT.md, at 10 fps.
See neil_robot/recorder.py for the fields and units.

Start it with the arm fully up and the gripper fully open: angles are logged
relative to where they are when the recorder starts.

    python scripts/record_episodes.py --task "pick up the cup" --driver adam
"""
import argparse
import json
import os
import queue
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gamepad import Gamepad  # noqa: E402
from gamepad_drive import BTN_A, BTN_B, BTN_X, BTN_Y, wheel_speeds  # noqa: E402
from neil_robot import config  # noqa: E402
from neil_robot.dashboard import IPHONE_CAMERA_ROTATION, IPHONE_CAMERA_URL, start_pi_script  # noqa: E402
from neil_robot.recorder import STATE_HZ, EpisodeRecorder, LatestFrame  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402

TASK = "kick the ball"  # must match neil_features.TASK in the training pipeline


def read_keys(keys: queue.Queue) -> None:
    for line in sys.stdin:
        keys.put(line.strip().lower())


def read_pi(stdout, rec: EpisodeRecorder, said: list) -> None:
    for line in stdout:
        if line.startswith("state "):
            rec.on_state(json.loads(line[6:]))
        else:
            said.append(line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=TASK, help="the instruction sentence, the same in every episode")
    ap.add_argument("--out", type=Path, default=ROOT / "episodes", help="folder the episodes go in")
    ap.add_argument("--driver", default=os.getenv("USER", ""), help="who is driving, saved in episode.json")
    ap.add_argument("--iphone-url", default=IPHONE_CAMERA_URL)
    ap.add_argument("--speed", type=int, default=30, help="wheel speed, 15..60")
    ap.add_argument("--arm-step", type=int, default=5, help="arm degrees per press")
    ap.add_argument("--grip-step", type=int, default=10, help="gripper degrees per press")
    ap.add_argument("--reverse-delay", type=float, default=1.0,
                    help="seconds the other wheel waits while one wheel reverses")
    args = ap.parse_args()
    if not config.MOTOR_MIN_SPEED <= args.speed <= config.MOTOR_MAX_SPEED:
        ap.error(f"speed must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")

    cameras = {"front": LatestFrame("front").start_pi_camera(),
               "top": LatestFrame("top").start_mjpeg(args.iphone_url, IPHONE_CAMERA_ROTATION)}
    rec = EpisodeRecorder(args.out, cameras, args.task, args.driver)
    keys: queue.Queue = queue.Queue()
    threading.Thread(target=read_keys, args=(keys,), daemon=True).start()
    settings = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
                "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER,
                "arm_speed": config.ARM_TEST_SPEED, "grip_speed": 25,
                "reverse_delay": args.reverse_delay, "state_hz": STATE_HZ}

    pad = Gamepad()
    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    stopped = None  # folder of an episode waiting for s / f / d
    with RPiClient() as pi:
        stdin, stdout = start_pi_script(pi, ROOT / "pi" / "gamepad_server.py", settings)
        said: list[str] = []
        threading.Thread(target=read_pi, args=(stdout, rec, said), daemon=True).start()

        def send(cmd: dict) -> None:
            stdin.write(json.dumps(cmd) + "\n")
            stdin.flush()

        def step(motor: str, robot_deg: int, sign: int) -> None:
            send({motor: sign * robot_deg})
            rec.step(motor, robot_deg)

        print(f"Ready. Episodes go to {args.out}. Enter starts/stops recording. Ctrl-C quits.")
        last_drive, last_buttons = (0, 0), [0] * 12
        try:
            while True:
                state = pad.wait(timeout_ms=50)
                rec.pad(state)
                drive = wheel_speeds(state, args.speed)
                if drive != last_drive:
                    send({"drive": [config.LEFT_WHEEL_SIGN_FORWARD * drive[0],
                                    config.RIGHT_WHEEL_SIGN_FORWARD * drive[1]]})
                    rec.drive(*drive)
                    last_drive = drive
                pressed = [b and not was for b, was in zip(state["buttons"], last_buttons)]
                last_buttons = state["buttons"]
                if pressed[BTN_X]:
                    step("arm", -args.arm_step, config.ARM_MOTOR_SIGN_DOWN)
                if pressed[BTN_B]:
                    step("arm", args.arm_step, config.ARM_MOTOR_SIGN_DOWN)
                if pressed[BTN_Y]:
                    step("grip", args.grip_step, config.GRIPPER_MOTOR_SIGN_OPEN)
                if pressed[BTN_A]:
                    step("grip", -args.grip_step, config.GRIPPER_MOTOR_SIGN_OPEN)

                while not keys.empty():
                    key = keys.get()
                    if stopped is not None:
                        if key in ("s", "f"):
                            print(f"\nSaved {rec.finish(success=key == 's').name} as "
                                  f"{'success' if key == 's' else 'failure'}.")
                            stopped = None
                        elif key == "d":
                            print(f"\nDeleted {rec.discard().name}.")
                            stopped = None
                    elif key == "" and rec.recording:
                        stopped = rec.stop()
                    elif key == "":
                        try:
                            print(f"\nRecording {rec.start().name} ...")
                        except RuntimeError as exc:
                            print(f"\n{exc}")

                if stopped is not None:
                    line = f"{stopped.name}: {rec.frames} frames. Type s (success), f (failure) or d (delete), Enter"
                elif rec.recording:
                    line = f"REC {rec.frames / 10:5.1f}s"
                else:
                    missing = rec.not_ready()
                    line = ("waiting for " + ", ".join(missing)) if missing else "ready, Enter to record"
                print("\r" + line[:110].ljust(110), end="", flush=True)
                if stdout.channel.exit_status_ready():
                    print("\nThe Pi script stopped. It said:\n" + "".join(said[-20:]))
                    break
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            if rec.recording:
                print(f"Deleted unfinished {rec.discard().name}.")
            pad.close()
            stdin.channel.shutdown_write()
            for cam in cameras.values():
                cam.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
