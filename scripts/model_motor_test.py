"""
Check that one model output can drive all of Neil's motors. THIS MOVES THE ROBOT for about
one second: put Neil on a block so its wheels are off the table, keep hands clear of the arm.

    python scripts/model_motor_test.py --replay logs/session_20261014_113509
    python scripts/model_motor_test.py --replay ... --dry        # print the commands, move nothing

1. Asks the policy server (policy_server/server.py) for one action chunk, from a recorded
   step (--replay; the Pi's cameras stay free).
2. Turns the first action's values 0..3 into commands, in the pick_cup order
   [left, right, arm, grip], robot terms (+ = forward / arm down / gripper open):
     wheels        speed = value x --scale, capped to --cap
     arm, gripper  a move of value x --deg-scale degrees, capped to --max-deg
   The base model's values are scaled units around +-2: use --scale 20 --deg-scale 50.
3. Starts pi/gamepad_server.py on the Pi, sends all four at once, stops the wheels after
   --seconds, moves the arm and gripper back, and prints what the motors measured.

Ctrl-C stops at any time: closing the connection stops every motor on the Pi (the arm
then goes limp, as with gamepad_drive.py).
"""
import argparse
import json
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neil_robot import config  # noqa: E402
from neil_robot.observation import ObservationSpec  # noqa: E402
from neil_robot.policy_client import DEFAULT_URL, PolicyClient  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402

def model_values(args) -> list[float]:
    spec = ObservationSpec.load(args.spec)
    session = Path(args.replay)
    row = json.loads((session / "steps.jsonl").read_text(encoding="utf-8").splitlines()[0])
    files = {row[s["camera"]]["file"]: (session / row[s["camera"]]["file"]).read_bytes()
             for s in spec.images.values()}
    client = PolicyClient(DEFAULT_URL)
    try:
        info = client.wait_ready(wait_s=10)
        print(f"Model: {info['policy']} ({info['checkpoint']}) on {info['device']}, "
              f"{info['chunk_size']} actions x {info['action_dim']} values")
        chunk = client.infer(spec.build(row, files))
    finally:
        client.close()
    first = chunk.actions[0]
    names = spec.action or [f"out.{i}" for i in range(len(first))]
    print(f"First action ({chunk.round_trip_ms:.0f} ms): "
          + "  ".join(f"{n} {v:+.3f}" for n, v in zip(names, first)))
    return first


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", required=True, metavar="SESSION_DIR", help="recorded session for the observation")
    ap.add_argument("--spec", default="specs/pick_cup.json")
    ap.add_argument("--scale", type=float, default=1.0, help="wheel speed = value x scale (default 1)")
    ap.add_argument("--cap", type=int, default=25, help="largest wheel speed, at most 40 (default 25)")
    ap.add_argument("--deg-scale", type=float, default=1.0, help="arm/gripper degrees = value x this (default 1)")
    ap.add_argument("--max-deg", type=int, default=15, help="largest arm/gripper move, at most 30 (default 15)")
    ap.add_argument("--seconds", type=float, default=1.0, help="how long the wheels run, at most 3 (default 1)")
    ap.add_argument("--dry", action="store_true", help="print the commands, don't connect to the Pi")
    args = ap.parse_args()
    if not 0 < args.cap <= 40 or not 0 < args.max_deg <= 30 or not 0 < args.seconds <= 3:
        ap.error("--cap must be 1..40, --max-deg 1..30, --seconds at most 3")

    first = model_values(args)
    if len(first) < 4:
        print(f"The model returns {len(first)} values; this needs 4.")
        return 1
    clamp = lambda v, c: max(-c, min(c, round(v)))
    left, right = (clamp(v * args.scale, args.cap) for v in first[:2])
    print(f"Wheels: left {first[0]:+.3f} -> speed {left:+d}, right {first[1]:+.3f} -> speed {right:+d} (cap {args.cap})")
    moves = {name: clamp(v * args.deg_scale, args.max_deg) for name, v in (("arm", first[2]), ("grip", first[3]))}
    print(f"Arm {first[2]:+.3f} -> move {moves['arm']:+d} deg (+ = down), "
          f"gripper {first[3]:+.3f} -> move {moves['grip']:+d} deg (+ = open), cap {args.max_deg}")
    if args.dry:
        print("--dry: not connecting to the Pi.")
        return 0

    settings = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
                "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER,
                "arm_speed": 25, "grip_speed": 25, "reverse_delay": 0, "state_hz": 10}
    code = (ROOT / "pi" / "gamepad_server.py").read_text()
    ports = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
             "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER}
    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    with RPiClient() as pi:
        stdin, stdout, _ = pi.connect().exec_command(
            f"python3 -u -c {shlex.quote(code)} {shlex.quote(json.dumps(settings))} 2>&1")
        for line in stdout:
            if line.startswith("ready "):
                break
            print("Pi:", line, end="")
        else:
            print("The Pi script stopped before it was ready.")
            return 1

        def send(cmd: dict) -> None:
            stdin.write(json.dumps(cmd) + "\n")
            stdin.flush()

        def state() -> str:
            for line in stdout:
                if line.startswith("state "):
                    s = json.loads(line[6:])
                    if "error" not in s:
                        return "  ".join(f"{n} {s[p][0]:+4d}/{s[p][1]:+6d}" for n, p in ports.items())
            return "?"

        try:
            print("(each motor: measured speed / raw angle)")
            print(f"Before:  {state()}")
            send({"drive": [config.LEFT_WHEEL_SIGN_FORWARD * left, config.RIGHT_WHEEL_SIGN_FORWARD * right],
                  "arm": config.ARM_MOTOR_SIGN_DOWN * moves["arm"],
                  "grip": config.GRIPPER_MOTOR_SIGN_OPEN * moves["grip"]})
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                print(f"Running: {state()}")
            send({"drive": [0, 0]})
            print(f"Stopped: {state()}")
            send({"arm": -config.ARM_MOTOR_SIGN_DOWN * moves["arm"],
                  "grip": -config.GRIPPER_MOTOR_SIGN_OPEN * moves["grip"]})  # back where they were
            for _ in range(8):
                last = state()
            print(f"Back:    {last}")
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            stdin.channel.shutdown_write()  # the Pi script stops every motor when stdin closes
    return 0


if __name__ == "__main__":
    sys.exit(main())
