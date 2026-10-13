"""
Drive the robot with the USB gamepad. THIS MOVES THE ROBOT: give it room, keep hands clear of the arm.

    D-pad up / down      drive forward / backward
    D-pad left / right   rotate counter-clockwise / clockwise on the spot
    X / B                raise / lower the arm, while held
    Y / A                open / close the gripper, while held
    Ctrl-C               stop and quit

    python scripts/gamepad_drive.py
    python scripts/gamepad_drive.py --drive-speed 40 --arm-deg-s 20

The wheels are speed controlled and go limp when released. The arm and gripper
are position controlled: holding a button moves their target angle, and on
release they hold that angle, so the gripper keeps its grip on an object. If the
laptop stops sending for config.PAD_WATCHDOG_S, the Pi stops the wheels and
freezes the arm and gripper by itself. On quit the motors go limp, so the arm
drops if it is raised.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gamepad import Gamepad  # noqa: E402
from neil_robot import config  # noqa: E402
from neil_robot.hardware import LiveMotors  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402

# Indexes in the contract's gamepad.axes / gamepad.buttons for this pad (see gamepad.py).
AXIS_DPAD_X, AXIS_DPAD_Y = 2, 3   # left -1 / right +1, up -1 / down +1
BTN_X, BTN_A, BTN_B, BTN_Y = 0, 1, 2, 3


def clamp(v: float, limit: int) -> int:
    return int(max(-limit, min(limit, v)))


def pad_to_command(pad: dict, drive: int, turn: int, arm: float, grip: float) -> dict:
    """Robot terms: wheel speeds + = forward; arm and grip in deg/s, + = down / open."""
    forward = -pad["axes"][AXIS_DPAD_Y]
    right = pad["axes"][AXIS_DPAD_X]  # + = rotate clockwise seen from above
    b = pad["buttons"]
    limit = max(drive, turn)
    return {
        "left": clamp(forward * drive + right * turn, limit),
        "right": clamp(forward * drive - right * turn, limit),
        "arm": (b[BTN_B] - b[BTN_X]) * arm,
        "grip": (b[BTN_Y] - b[BTN_A]) * grip,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drive-speed", type=int, default=config.PAD_DRIVE_SPEED)
    ap.add_argument("--turn-speed", type=int, default=config.PAD_TURN_SPEED)
    ap.add_argument("--arm-deg-s", type=float, default=config.PAD_ARM_DEG_S,
                    help="how fast the arm moves, motor degrees per second")
    ap.add_argument("--gripper-deg-s", type=float, default=config.PAD_GRIPPER_DEG_S,
                    help="how fast the gripper moves, motor degrees per second")
    args = ap.parse_args()
    if not 5 <= args.arm_deg_s <= 120:
        ap.error("arm deg/s must be 5..120")
    if not 10 <= args.gripper_deg_s <= 360:
        ap.error("gripper deg/s must be 10..360")
    for name in ("drive_speed", "turn_speed"):
        if not config.MOTOR_MIN_SPEED <= getattr(args, name) <= config.MOTOR_MAX_SPEED:
            ap.error(f"{name.replace('_', ' ')} must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")

    pad = Gamepad()
    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    period = 1 / config.PAD_SEND_HZ
    with RPiClient() as pi, LiveMotors(client=pi) as live:
        print("Ready. D-pad drives, X/B arm up/down, Y/A gripper open/close. Ctrl-C to quit.")
        try:
            while True:
                t0 = time.monotonic()
                cmd = pad_to_command(pad.poll(), args.drive_speed, args.turn_speed,
                                     args.arm_deg_s, args.gripper_deg_s)
                live.send(**cmd)
                print("\r" + "  ".join(f"{k} {v:+4.0f}" for k, v in cmd.items()) + "   ", end="", flush=True)
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            pad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
