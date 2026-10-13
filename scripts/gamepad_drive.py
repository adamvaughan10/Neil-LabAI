"""
Drive the robot with the USB gamepad. THIS MOVES THE ROBOT: give it room, keep hands clear of the arm.

    D-pad up / down      both wheels forward / backward while held
    D-pad left / right   rotate counter-clockwise / clockwise on the spot while held
    X / B                arm up / down by --arm-step degrees per press
    Y / A                gripper open / close by --grip-step degrees per press
    Ctrl-C               stop and quit (the motors go limp, so the arm drops)

    python scripts/gamepad_drive.py
    python scripts/gamepad_drive.py --speed 40 --grip-step 20

The Pi side is pi/gamepad_server.py, a plain buildhat script that this sends over
SSH and runs. Commands go only when a button changes.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gamepad import Gamepad  # noqa: E402
from neil_robot import config  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402

# Indexes in gamepad.axes / gamepad.buttons for this pad (see gamepad.py).
AXIS_DPAD_X, AXIS_DPAD_Y = 2, 3   # left -1 / right +1, up -1 / down +1
BTN_X, BTN_A, BTN_B, BTN_Y = 0, 1, 2, 3


def wheel_speeds(pad: dict, speed: int) -> tuple[int, int]:
    """Robot-terms (left, right) wheel speeds, + = forward."""
    forward = -pad["axes"][AXIS_DPAD_Y]
    right = pad["axes"][AXIS_DPAD_X]
    if forward:
        return int(forward * speed), int(forward * speed)
    return int(right * speed), int(-right * speed)  # rotate on the spot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speed", type=int, default=30, help="wheel speed, 15..60")
    ap.add_argument("--arm-step", type=int, default=15, help="arm degrees per press")
    ap.add_argument("--grip-step", type=int, default=10, help="gripper degrees per press")
    args = ap.parse_args()
    if not config.MOTOR_MIN_SPEED <= args.speed <= config.MOTOR_MAX_SPEED:
        ap.error(f"speed must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")

    settings = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
                "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER,
                "arm_speed": config.ARM_TEST_SPEED, "grip_speed": 25}
    code = (ROOT / "pi" / "gamepad_server.py").read_text()
    # Motor degrees for one press, after the mounting sign flips.
    arm_down = config.ARM_MOTOR_SIGN_DOWN * args.arm_step
    grip_open = config.GRIPPER_MOTOR_SIGN_OPEN * args.grip_step

    pad = Gamepad()
    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    with RPiClient() as pi:
        stdin, stdout, _ = pi.connect().exec_command(
            f"python3 -u -c {shlex.quote(code)} {shlex.quote(json.dumps(settings))} 2>&1")
        for line in stdout:  # wait for the HAT (it may load firmware first)
            if line.startswith("ready "):
                start = json.loads(line[len("ready "):])  # encoder angles at startup
                break
            print("Pi:", line, end="")
        else:
            print("The Pi script stopped before it was ready.")
            return 1

        # The target the controller sets, in robot terms and the dataset's names: wheel
        # speeds (+ = forward) and arm / gripper encoder angles (+ = down / open). The
        # motors then move to meet it. Printed on every change.
        target = {"left_wheel.vel": 0, "right_wheel.vel": 0,
                  "arm.pos": config.ARM_MOTOR_SIGN_DOWN * start["arm"],
                  "grip.pos": config.GRIPPER_MOTOR_SIGN_OPEN * start["grip"]}

        def send(cmd: dict) -> None:
            stdin.write(json.dumps(cmd) + "\n")
            stdin.flush()
            print("target  " + "  ".join(f"{k} {v:+5.0f}" for k, v in target.items()))

        print("Ready. D-pad drives, X/B arm up/down, Y/A gripper open/close. Ctrl-C to quit.")
        print("start   " + "  ".join(f"{k} {v:+5.0f}" for k, v in target.items()))
        last_drive, last_buttons = (0, 0), [0] * 12
        try:
            while True:
                state = pad.wait()
                left, right = wheel_speeds(state, args.speed)
                drive = (config.LEFT_WHEEL_SIGN_FORWARD * left, config.RIGHT_WHEEL_SIGN_FORWARD * right)
                if drive != last_drive:
                    target["left_wheel.vel"], target["right_wheel.vel"] = left, right
                    send({"drive": list(drive)})
                    last_drive = drive
                pressed = [b and not was for b, was in zip(state["buttons"], last_buttons)]
                last_buttons = state["buttons"]
                for button, part, motor_deg in ((BTN_X, "arm", -arm_down), (BTN_B, "arm", arm_down),
                                                 (BTN_Y, "grip", grip_open), (BTN_A, "grip", -grip_open)):
                    if pressed[button]:
                        sign = config.ARM_MOTOR_SIGN_DOWN if part == "arm" else config.GRIPPER_MOTOR_SIGN_OPEN
                        target[f"{part}.pos"] += sign * motor_deg
                        send({part: motor_deg})
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            pad.close()
            stdin.channel.shutdown_write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
