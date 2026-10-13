"""
Drive the robot with the USB gamepad. THIS MOVES THE ROBOT: give it room, keep hands clear of the arm.

    D-pad up / down      both wheels forward / backward while held
    D-pad left / right   rotate counter-clockwise / clockwise on the spot while held
    X / B                arm up / down: X raises it to --arm-up angle (-13, as shown in the live
                         line), B lowers it back to where it started (two positions only)
    Y / A                gripper open / close by --grip-step degrees per press
    Ctrl-C               stop and quit (the motors go limp, so the arm drops)

    python scripts/gamepad_drive.py
    python scripts/gamepad_drive.py --speed 40 --grip-step 20
    python scripts/gamepad_drive.py --record        also record VLA data until Ctrl-C

The Pi side is pi/gamepad_server.py, a plain buildhat script that this sends over
SSH and runs. Commands go only when a button changes. While running it shows a live
line with the action (the target the controller sets) and the motors' measured values.

--record records the whole run with neil_robot/recorder.py, like stream_cameras.py
(see README, "Synced recording"): both cameras plus, on every step, "motors" (what
the motors report) and "action" (the controller's target), into logs/session_<date>_<time>/.
Motor readings come from pi/gamepad_server.py, since only one program can open the HAT.
"""
import argparse
import json
import shlex
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gamepad import Gamepad  # noqa: E402
from neil_robot import clock, config  # noqa: E402
from neil_robot.motor_stream import ROLES  # noqa: E402
from neil_robot.recorder import SyncRecorder  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402
from neil_robot.streams import ExternalCameraStream, PiCameraStream  # noqa: E402

# Indexes in gamepad.axes / gamepad.buttons for this pad (see gamepad.py).
AXIS_DPAD_X, AXIS_DPAD_Y = 2, 3   # left -1 / right +1, up -1 / down +1
BTN_X, BTN_A, BTN_B, BTN_Y = 0, 1, 2, 3


def wheel_speeds(pad: dict, speed: int) -> tuple[int, int]:
    """Robot-terms (left, right) wheel speeds, + = forward."""
    forward = -pad["axes"][AXIS_DPAD_Y]
    right = pad["axes"][AXIS_DPAD_X]
    # Turning wins over driving: this pad often reports left as up+left, which
    # used to drive both wheels forward instead of turning.
    if right:
        return int(right * speed), int(-right * speed)  # rotate on the spot
    return int(forward * speed), int(forward * speed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speed", type=int, default=30, help="wheel speed, 15..60")
    ap.add_argument("--arm-up", type=int, default=-13,
                    help="arm angle X raises it to, as shown in the live line (- = up); "
                         "encoder degrees, which reset when the Build HAT powers up")
    ap.add_argument("--arm-speed", type=int, default=25,
                    help="arm motor speed for each step, 5..50 (at 10 the arm can't lift itself)")
    ap.add_argument("--reverse-delay", type=float, default=1.0,
                    help="seconds the other wheel waits while one wheel reverses")
    ap.add_argument("--grip-step", type=int, default=10, help="gripper degrees per press")
    ap.add_argument("--record", action="store_true",
                    help="record cameras, motors and the controller's target until Ctrl-C")
    ap.add_argument("--fps", type=float, default=config.RECORD_FPS, help="recording steps per second (default 15)")
    ap.add_argument("--no-external", action="store_true", help="record the Pi camera only")
    ap.add_argument("--external-url", default=config.EXTERNAL_CAMERA_URL)
    ap.add_argument("--external-rotation", type=int, choices=(0, 90, 180, 270),
                    default=config.EXTERNAL_CAMERA_ROTATION)
    args = ap.parse_args()
    if not config.MOTOR_MIN_SPEED <= args.speed <= config.MOTOR_MAX_SPEED:
        ap.error(f"speed must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")
    if not 5 <= args.arm_speed <= 50:
        ap.error("arm speed must be 5..50")

    settings = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
                "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER,
                "arm_speed": args.arm_speed, "grip_speed": 25,
                "reverse_delay": args.reverse_delay,
                "state_hz": config.MOTOR_STREAM_HZ if args.record else 10}
    code = (ROOT / "pi" / "gamepad_server.py").read_text()
    # Motor degrees for one press, after the mounting sign flips.
    grip_open = config.GRIPPER_MOTOR_SIGN_OPEN * args.grip_step

    cameras = {}
    if args.record:
        cameras["pi"] = PiCameraStream()
        if not args.no_external:
            cameras["external"] = ExternalCameraStream(args.external_url, args.external_rotation)
        for name, cam in cameras.items():
            print(f"Connecting to {name} camera ({cam.url}) ...")
            cam.start()

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

        # Robot terms and the dataset's names: wheel speeds + = forward, arm / gripper
        # encoder angles + = down / open. `action` is the target the controller sets;
        # `measured` is what the motors report back as they move to meet it.
        signs = {"left_wheel.vel": (config.PORT_LEFT_WHEEL, 0, config.LEFT_WHEEL_SIGN_FORWARD),
                 "right_wheel.vel": (config.PORT_RIGHT_WHEEL, 0, config.RIGHT_WHEEL_SIGN_FORWARD),
                 "arm.pos": (config.PORT_ARM, 1, config.ARM_MOTOR_SIGN_DOWN),
                 "grip.pos": (config.PORT_GRIPPER, 1, config.GRIPPER_MOTOR_SIGN_OPEN)}
        action = {"left_wheel.vel": 0, "right_wheel.vel": 0,
                  "arm.pos": config.ARM_MOTOR_SIGN_DOWN * start["arm"],
                  "grip.pos": config.GRIPPER_MOTOR_SIGN_OPEN * start["grip"]}
        measured = {}
        # The same target in raw motor terms, shaped like the recorder's "motors" entry.
        target = {"drive": [0, 0], "arm": start["arm"], "grip": start["grip"], "ts": clock.now(), "seq": 0}
        latest = {}  # newest Pi state line: {"state", "ts", "seq"}

        short = {"left_wheel.vel": "L", "right_wheel.vel": "R", "arm.pos": "arm", "grip.pos": "grip"}

        last_shown = [None]

        def show() -> None:  # a new line whenever a displayed value changes
            fmt = lambda d: " ".join(f"{short[k]} {d[k]:+4.0f}" if k in d else f"{short[k]}    ?" for k in action)
            line = f"action {fmt(action)}  |  measured {fmt(measured)}"
            if line != last_shown[0]:
                print(line, flush=True)
                last_shown[0] = line

        def read_pi() -> None:  # the Pi's state lines, 10 a second
            for line in stdout:
                if not line.startswith("state "):
                    print("Pi:", line, end="")
                    continue
                state = json.loads(line[len("state "):])
                if "error" in state:
                    continue
                latest.update(state=state, ts=clock.now(), seq=latest.get("seq", -1) + 1)
                for name, (port, i, sign) in signs.items():
                    measured[name] = sign * state[port][i]
                show()

        threading.Thread(target=read_pi, daemon=True).start()

        def send(cmd: dict) -> None:
            stdin.write(json.dumps(cmd) + "\n")
            stdin.flush()
            show()

        def motors_step(t: float) -> dict | None:  # recorder extra: what the motors report
            if not latest:
                return None
            out = {"seq": latest["seq"], "ts": round(latest["ts"], 6), "age_ms": round((t - latest["ts"]) * 1000, 2)}
            for port, role in ROLES.items():
                speed, pos, apos = (latest["state"][port] + [None])[:3]
                out[role] = {"port": port, "pos_deg": pos, "abs_pos_deg": apos, "speed": speed}
            return out

        def action_step(t: float) -> dict:
            """Recorder extra: the controller's target, in exactly the "motors" format.
            Wheels are speed controlled and the arm / gripper angle controlled, so the
            value the controller doesn't set is None."""
            ports = {"left_wheel": config.PORT_LEFT_WHEEL, "right_wheel": config.PORT_RIGHT_WHEEL,
                     "gripper": config.PORT_GRIPPER, "arm": config.PORT_ARM}
            speeds = {"left_wheel": target["drive"][0], "right_wheel": target["drive"][1]}
            angles = {"arm": target["arm"], "gripper": target["grip"]}
            out = {"seq": target["seq"], "ts": round(target["ts"], 6), "age_ms": round((t - target["ts"]) * 1000, 2)}
            for role in ROLES.values():
                out[role] = {"port": ports[role], "pos_deg": angles.get(role), "abs_pos_deg": None,
                             "speed": speeds.get(role)}
            return out

        recorder = None
        if args.record:
            recorder = SyncRecorder(cameras, fps=args.fps, extras={"motors": motors_step, "action": action_step})
            recorder.start()
            print(f"Recording at {args.fps:g} fps to {recorder.out_dir} until Ctrl-C ...")

        print("Ready. D-pad drives, X raises / B lowers the arm, Y/A gripper open/close. Ctrl-C to quit.")
        print("L/R = wheel speed (+ forward), arm = angle (+ down), grip = angle (+ open)")
        last_drive, last_buttons = (0, 0), [0] * 12
        try:
            while True:
                state = pad.wait()
                left, right = wheel_speeds(state, args.speed)
                drive = (config.LEFT_WHEEL_SIGN_FORWARD * left, config.RIGHT_WHEEL_SIGN_FORWARD * right)
                if drive != last_drive:
                    action["left_wheel.vel"], action["right_wheel.vel"] = left, right
                    target.update(drive=list(drive), ts=clock.now(), seq=target["seq"] + 1)
                    send({"drive": list(drive)})
                    last_drive = drive
                pressed = [b and not was for b, was in zip(state["buttons"], last_buttons)]
                last_buttons = state["buttons"]
                # Arm: two positions, down (where it started) and raised (--arm-up). The command
                # is the turn from where the arm really is to that position.
                for button, raised in ((BTN_X, True), (BTN_B, False)):
                    goal = config.ARM_MOTOR_SIGN_DOWN * args.arm_up if raised else start["arm"]
                    if pressed[button] and target["arm"] != goal:
                        now = latest["state"][config.PORT_ARM][1] if latest else target["arm"]
                        target.update(arm=goal, ts=clock.now(), seq=target["seq"] + 1)
                        action["arm.pos"] = config.ARM_MOTOR_SIGN_DOWN * goal
                        send({"arm": goal - now})
                for button, part, motor_deg in ((BTN_Y, "grip", grip_open), (BTN_A, "grip", -grip_open)):
                    if pressed[button]:
                        sign = config.GRIPPER_MOTOR_SIGN_OPEN
                        # The Pi turns the motor motor_deg from wherever it is when the move runs.
                        # If the last move fell short (the gripper closing on an object), count
                        # from where the motor really is, so the recorded target stays where the
                        # motor is actually headed.
                        now = latest["state"][config.PORT_GRIPPER][1] if latest else target[part]
                        if abs(target[part] - now) >= abs(motor_deg):
                            target[part] = now
                        target[part] += motor_deg
                        action[f"{part}.pos"] = sign * target[part]
                        target.update(ts=clock.now(), seq=target["seq"] + 1)
                        send({part: motor_deg})
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            pad.close()
            stdin.channel.shutdown_write()
            if recorder is not None:
                print("Saving the recording ...")
                summary = recorder.stop()
                print(f"Recorded {summary['steps']} steps at {summary['fps']:g} fps to {recorder.out_dir}"
                      + (f" WRITE ERROR: {summary['writer_error']}" if summary["writer_error"] else ""))
            for cam in cameras.values():
                cam.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
