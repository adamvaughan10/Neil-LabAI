"""
Drive the robot with the USB gamepad. THIS MOVES THE ROBOT: give it room, keep hands clear of the arm.

    D-pad up / down      both wheels forward / backward while held
    D-pad left / right   rotate counter-clockwise / clockwise on the spot while held
                         The wheels move like the gripper: while the D-pad is held each wheel
                         turns run_for_degrees steps, --wheel-deg-s degrees a second, and its
                         target angle is recorded, wrapping at a full turn
    X / B                arm up / down: B lowers it to its resting angle (--arm-down-abs), X
                         raises it --arm-raise degrees (20) above that (two positions only).
                         Uses the motor's absolute angle, so it knows where the arm is even
                         if it starts up or the Build HAT kept counting from an earlier run
    Y / A                gripper open / close by --grip-step degrees per press
    Ctrl-C               stop and quit (the motors go limp, so the arm drops)

    python scripts/gamepad_drive.py
    python scripts/gamepad_drive.py --wheel-deg-s 150 --grip-step 20
    python scripts/gamepad_drive.py --record        also record VLA data until Ctrl-C

The Pi side is pi/gamepad_server.py, a plain buildhat script that this sends over
SSH and runs. Commands go when a button changes, and about 10 times a second while the
D-pad is held. While running it shows a live line with the action (the target the
controller sets) and the motors' measured values.

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
import time
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


def wheel_directions(pad: dict) -> tuple[int, int]:
    """Robot-terms (left, right) wheel directions: 1 = forward, -1 = backward, 0 = still."""
    forward = int(-pad["axes"][AXIS_DPAD_Y])
    right = int(pad["axes"][AXIS_DPAD_X])
    # Turning wins over driving: this pad often reports left as up+left, which
    # used to drive both wheels forward instead of turning.
    if right:
        return right, -right  # rotate on the spot
    return forward, forward


def wrap(deg: float) -> float:
    """An angle in (-180, 180]: a full turn later it reads the same again."""
    return 180 - (180 - deg) % 360


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speed", type=int, default=30, help="wheel motor speed for each degree step, 15..60")
    ap.add_argument("--wheel-deg-s", type=float, default=200,
                    help="wheel degrees per second while the D-pad is held")
    ap.add_argument("--arm-raise", type=int, default=20,
                    help="degrees X raises the arm above its resting (down) angle")
    ap.add_argument("--arm-down-abs", type=int, default=12,
                    help="the arm motor's absolute angle (abs_pos_deg, -180..180) with the arm resting down; "
                         "12 measured on 2026-10-13/14")
    ap.add_argument("--arm-sag", type=float, nargs=2, default=(7, 3), metavar=("UP", "DOWN"),
                    help="degrees the arm settles below its goal after a move up / down (gravity and "
                         "gear slack); commands aim that much higher to cancel it. Measured on 2026-10-13")
    ap.add_argument("--arm-speed", type=int, default=25,
                    help="arm motor speed for each step, 5..50 (at 10 the arm can't lift itself)")
    ap.add_argument("--grip-step", type=int, default=10, help="gripper degrees per press")
    ap.add_argument("--record", action="store_true",
                    help="record cameras, motors and the controller's target until Ctrl-C")
    ap.add_argument("--fps", type=float, default=10,
                    help="recording steps per second (default 10, the VLA pipeline's rate, so every step is a frame)")
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
                "arm_speed": args.arm_speed, "grip_speed": 25, "wheel_speed": args.speed,
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

        # Robot terms and the dataset's names: encoder angles + = forward / down / open, the
        # wheels' wrapped to -180..180 as recorded. `action` is the target the controller sets;
        # `measured` is what the motors report back as they move to meet it.
        signs = {"left_wheel.pos": (config.PORT_LEFT_WHEEL, config.LEFT_WHEEL_SIGN_FORWARD),
                 "right_wheel.pos": (config.PORT_RIGHT_WHEEL, config.RIGHT_WHEEL_SIGN_FORWARD),
                 "arm.pos": (config.PORT_ARM, config.ARM_MOTOR_SIGN_DOWN),
                 "grip.pos": (config.PORT_GRIPPER, config.GRIPPER_MOTOR_SIGN_OPEN)}
        action = {"left_wheel.pos": wrap(config.LEFT_WHEEL_SIGN_FORWARD * start.get("left", 0)),
                  "right_wheel.pos": wrap(config.RIGHT_WHEEL_SIGN_FORWARD * start.get("right", 0)),
                  "arm.pos": config.ARM_MOTOR_SIGN_DOWN * start["arm"],
                  "grip.pos": config.GRIPPER_MOTOR_SIGN_OPEN * start["grip"]}
        measured = {}
        # The same target in raw motor terms, shaped like the recorder's "motors" entry.
        target = {"arm": start["arm"], "grip": start["grip"], "ts": clock.now(), "seq": 0,
                  "wheel": [start.get("left", 0), start.get("right", 0)]}  # wheels: raw target angles
        wheel_sign = (config.LEFT_WHEEL_SIGN_FORWARD, config.RIGHT_WHEEL_SIGN_FORWARD)
        owed, last_wheel_send = [0.0, 0.0], 0.0  # robot-terms wheel degrees not sent yet
        latest = {}  # newest Pi state line: {"state", "ts", "seq"}
        hat_calls = []  # every Build HAT call the Pi made, in order, stamped on arrival
        pad_seen = {"buttons": [0] * 4, "dpad": [0, 0], "ts": clock.now(), "seq": 0}  # since the last step
        pad_lock = threading.Lock()
        pad_now = [{"axes": [0.0] * 4, "buttons": [0] * 12}]  # newest pad state
        pad_prev = [pad_now[0]]

        short = {"left_wheel.pos": "L", "right_wheel.pos": "R", "arm.pos": "arm", "grip.pos": "grip"}

        last_shown = [None]

        def show() -> None:  # a new line whenever a displayed value changes
            fmt = lambda d: " ".join(f"{short[k]} {d[k]:+4.0f}" if k in d else f"{short[k]}    ?" for k in action)
            line = f"action {fmt(action)}  |  measured {fmt(measured)}"
            if line != last_shown[0]:
                print(line, flush=True)
                last_shown[0] = line

        def arm_goals() -> tuple[int, int]:
            """(down, up) as encoder angles. The encoder counts from wherever the arm was
            when the Build HAT powered up, but the absolute angle is the shaft's own, so the
            resting angle is found from it."""
            _, pos, apos = latest["state"][config.PORT_ARM][:3]
            down = pos - apos + args.arm_down_abs
            return down, down - config.ARM_MOTOR_SIGN_DOWN * args.arm_raise

        def read_pi() -> None:  # the Pi's state lines, 10 a second
            for line in stdout:
                if line.startswith("hat "):
                    hat_calls.append({**json.loads(line[len("hat "):]), "ts": clock.now()})
                    continue
                if not line.startswith("state "):
                    print("Pi:", line, end="")
                    continue
                state = json.loads(line[len("state "):])
                if "error" in state:
                    continue
                latest.update(state=state, ts=clock.now(), seq=latest.get("seq", -1) + 1)
                if "arm_known" not in latest:  # first reading: is the arm up or down right now?
                    down, up = arm_goals()
                    pos = state[config.PORT_ARM][1]
                    target["arm"] = up if abs(pos - up) < abs(pos - down) else down
                    action["arm.pos"] = config.ARM_MOTOR_SIGN_DOWN * target["arm"]
                    latest["arm_known"] = True
                for name, (port, sign) in signs.items():
                    angle = sign * state[port][1]
                    measured[name] = wrap(angle) if "wheel" in name else angle
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
            Every motor is angle controlled, so its target is pos_deg and speed is None.
            "vector" is the same target as one list, in robot terms like the live line
            (+ = forward / down / open), named like the "gamepad" extra's vector; its
            wheel angles wrap to -180..180."""
            ports = {"left_wheel": config.PORT_LEFT_WHEEL, "right_wheel": config.PORT_RIGHT_WHEEL,
                     "gripper": config.PORT_GRIPPER, "arm": config.PORT_ARM}
            angles = {"left_wheel": target["wheel"][0], "right_wheel": target["wheel"][1],
                      "arm": target["arm"], "gripper": target["grip"]}
            out = {"seq": target["seq"], "ts": round(target["ts"], 6), "age_ms": round((t - target["ts"]) * 1000, 2)}
            for role in ROLES.values():
                out[role] = {"port": ports[role], "pos_deg": angles[role], "abs_pos_deg": None, "speed": None}
            out["names"] = ["left_wheel.pos", "right_wheel.pos", "arm.pos", "grip.pos"]
            wheels = [round(wrap(sign * deg), 1) for sign, deg in zip(wheel_sign, target["wheel"])]
            out["vector"] = wheels + [config.ARM_MOTOR_SIGN_DOWN * target["arm"],
                                      config.GRIPPER_MOTOR_SIGN_OPEN * target["grip"]]
            return out

        seen = [0]  # hat_calls already given to a step

        def hat_step(t: float) -> dict | None:
            """Recorder extra: the Build HAT calls the Pi actually made, in the "motors"
            format plus two keys. Per motor:
              speed    the speed of the last run_for_degrees (None after stop)
              degrees  degrees of every run_for_degrees made since the previous step,
                       summed (0 when there was none)
              call     the last call: "run_for_degrees", or "stop" (the wheels, on quitting)
            "new" lists every call made since the previous step, with its time."""
            calls = hat_calls[:]  # appended to by read_pi; a copy is safe to read
            new, seen[0] = calls[seen[0]:], len(calls)
            if not calls:
                return None
            out = {"seq": len(calls), "ts": round(calls[-1]["ts"], 6),
                   "age_ms": round((t - calls[-1]["ts"]) * 1000, 2)}
            for port, role in ROLES.items():
                last = next((c for c in reversed(calls) if c["port"] == port), None)
                out[role] = {"port": port, "pos_deg": None, "abs_pos_deg": None,
                             "speed": (last or {}).get("speed"),
                             "degrees": sum(c["degrees"] for c in new
                                            if c["port"] == port and c["call"] == "run_for_degrees"),
                             "call": last and last["call"],
                             "age_ms": last and round((t - last["ts"]) * 1000, 2)}
            out["new"] = [{"port": c["port"], "call": c["call"], "speed": c.get("speed"),
                           "degrees": c.get("degrees"), "ts": round(c["ts"], 6)} for c in new]
            return out

        def gamepad_step(t: float) -> dict:
            """Recorder extra: which buttons were pressed, as a fixed vector.
            vector = [dpad_x, dpad_y, X, A, B, Y]: dpad_x left -1 / right +1, dpad_y up +1 /
            down -1, buttons 1 when pressed at any moment since the previous step (a tap
            shorter than a step still counts), else 0."""
            with pad_lock:
                seen = dict(pad_seen)
                cur = pad_now[0]
                pad_seen.update(buttons=[cur["buttons"][b] for b in (BTN_X, BTN_A, BTN_B, BTN_Y)],
                                dpad=[cur["axes"][AXIS_DPAD_X], -cur["axes"][AXIS_DPAD_Y]])
            vector = [int(round(v)) for v in seen["dpad"]] + seen["buttons"]
            return {"seq": seen["seq"], "ts": round(seen["ts"], 6), "age_ms": round((t - seen["ts"]) * 1000, 2),
                    "names": ["dpad_x", "dpad_y", "X", "A", "B", "Y"], "vector": vector,
                    "axes": cur["axes"], "buttons": cur["buttons"]}

        recorder = None
        if args.record:
            recorder = SyncRecorder(cameras, fps=args.fps, extras={"motors": motors_step, "action": action_step,
                                                                      "hat_commands": hat_step,
                                                                      "gamepad": gamepad_step})
            deadline = time.monotonic() + 10
            while not latest and time.monotonic() < deadline:  # so step 0 already has the motors
                time.sleep(0.05)
            recorder.start()
            print(f"Recording at {args.fps:g} fps to {recorder.out_dir} until Ctrl-C ...")

        print("Ready. D-pad drives, X raises / B lowers the arm, Y/A gripper open/close. Ctrl-C to quit.")
        print("L/R = wheel angle (+ forward, -180..180), arm = angle (+ down), grip = angle (+ open)")
        last_buttons, last_t = [0] * 12, time.monotonic()
        try:
            while True:
                state = pad.wait(timeout_ms=50)  # wakes at least 20 times a second, to turn held wheels
                now_t = time.monotonic()
                dt, last_t = now_t - last_t, now_t
                with pad_lock:  # remember everything pressed until the recorder's next step
                    pad_now[0] = state
                    for i, b in enumerate((BTN_X, BTN_A, BTN_B, BTN_Y)):
                        pad_seen["buttons"][i] |= state["buttons"][b]
                    dpad = [state["axes"][AXIS_DPAD_X], -state["axes"][AXIS_DPAD_Y]]
                    if any(dpad):  # the latest direction held, even if let go before the step
                        pad_seen["dpad"] = dpad
                    if state["buttons"] != last_buttons or state["axes"] != pad_prev[0]["axes"]:
                        pad_seen.update(ts=clock.now(), seq=pad_seen["seq"] + 1)
                    pad_prev[0] = state
                # Like the gripper: turn each wheel in degree steps while the D-pad is held,
                # sent about 10 times a second so the moves stay small.
                for i, direction in enumerate(wheel_directions(state)):
                    owed[i] += direction * args.wheel_deg_s * dt
                if now_t - last_wheel_send >= 0.1 and any(abs(o) >= 1 for o in owed):
                    robot_deg = [int(o) for o in owed]
                    owed = [o - d for o, d in zip(owed, robot_deg)]
                    raw = [sign * d for sign, d in zip(wheel_sign, robot_deg)]
                    target["wheel"] = [w + d for w, d in zip(target["wheel"], raw)]
                    target.update(ts=clock.now(), seq=target["seq"] + 1)
                    action["left_wheel.pos"], action["right_wheel.pos"] = (
                        round(wrap(sign * w)) for sign, w in zip(wheel_sign, target["wheel"]))
                    send({"wheel_deg": raw})
                    last_wheel_send = now_t
                pressed = [b and not was for b, was in zip(state["buttons"], last_buttons)]
                last_buttons = state["buttons"]
                # Arm: two positions, down (--arm-down-abs) and raised (--arm-raise above). The command
                # is the turn from where the arm really is to that position, aimed --arm-sag
                # higher because the arm settles that far below where it is sent. The recorded
                # target is the goal itself.
                for button, raised in ((BTN_X, True), (BTN_B, False)):
                    if not pressed[button] or not latest:
                        continue
                    goal = arm_goals()[1 if raised else 0]
                    if target["arm"] != goal:
                        now = latest["state"][config.PORT_ARM][1] if latest else target["arm"]
                        target.update(arm=goal, ts=clock.now(), seq=target["seq"] + 1)
                        action["arm.pos"] = config.ARM_MOTOR_SIGN_DOWN * goal
                        going_up = config.ARM_MOTOR_SIGN_DOWN * (goal - now) < 0
                        sag = args.arm_sag[0] if going_up else args.arm_sag[1]
                        send({"arm": round(goal - now - config.ARM_MOTOR_SIGN_DOWN * sag)})
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
