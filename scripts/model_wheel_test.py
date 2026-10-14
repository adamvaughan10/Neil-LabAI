"""
Check that a model output can drive a wheel. THIS MOVES ONE WHEEL: put Neil on a block
so its wheels are off the table, or give it room.

    python scripts/model_wheel_test.py --replay logs/session_20261014_113509
    python scripts/model_wheel_test.py --replay ... --dry        # print the speed, move nothing

1. Asks the policy server (policy_server/server.py) for one action chunk, from a recorded
   step (--replay; the Pi's cameras stay free).
2. Takes one number of the first action (--index, default 0 = the left wheel for the
   pick_cup model) and turns it into a wheel speed: value x --scale, capped to --cap.
   The pick_cup model's wheel actions are already speeds (-100..100, + = forward), so
   --scale 1. The base model's are scaled units around +-2: use --scale 20 to see them.
3. Starts pi/gamepad_server.py on the Pi, runs that wheel at the speed for --seconds,
   stops it, and prints the wheel's measured speed and angle before and after.

Ctrl-C stops the wheel at any time: closing the connection stops every motor on the Pi.
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

WHEELS = {"left": (config.PORT_LEFT_WHEEL, config.LEFT_WHEEL_SIGN_FORWARD),
          "right": (config.PORT_RIGHT_WHEEL, config.RIGHT_WHEEL_SIGN_FORWARD)}


def model_value(args) -> float:
    spec = ObservationSpec.load(args.spec)
    session = Path(args.replay)
    row = json.loads((session / "steps.jsonl").read_text(encoding="utf-8").splitlines()[args.step])
    files = {row[s["camera"]]["file"]: (session / row[s["camera"]]["file"]).read_bytes()
             for s in spec.images.values()}
    client = PolicyClient(args.server)
    try:
        info = client.wait_ready(wait_s=10)
        print(f"Model: {info['policy']} ({info['checkpoint']}) on {info['device']}, "
              f"{info['chunk_size']} actions x {info['action_dim']} values")
        chunk = client.infer(spec.build(row, files, args.task))
    finally:
        client.close()
    first = chunk.actions[0]
    names = spec.action or [f"out.{i}" for i in range(len(first))]
    print(f"First action ({chunk.round_trip_ms:.0f} ms): "
          + "  ".join(f"{n} {v:+.3f}" for n, v in zip(names, first)))
    return first[args.index]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", required=True, metavar="SESSION_DIR", help="recorded session for the observation")
    ap.add_argument("--step", type=int, default=0, help="which recorded step to send (default 0)")
    ap.add_argument("--spec", default="specs/pick_cup.json")
    ap.add_argument("--task", help="language instruction (default: the spec's)")
    ap.add_argument("--server", default=DEFAULT_URL)
    ap.add_argument("--index", type=int, default=0, help="which action value drives the wheel (default 0)")
    ap.add_argument("--wheel", choices=WHEELS, default="left")
    ap.add_argument("--scale", type=float, default=1.0, help="wheel speed = value x scale (default 1)")
    ap.add_argument("--cap", type=int, default=25, help="largest wheel speed allowed, at most 40 (default 25)")
    ap.add_argument("--seconds", type=float, default=1.0, help="how long the wheel runs, at most 3 (default 1)")
    ap.add_argument("--dry", action="store_true", help="print the speed, don't connect to the Pi")
    args = ap.parse_args()
    if not 0 < args.cap <= 40 or not 0 < args.seconds <= 3:
        ap.error("--cap must be 1..40 and --seconds at most 3")

    value = model_value(args)
    speed = max(-args.cap, min(args.cap, round(value * args.scale)))
    port, sign = WHEELS[args.wheel]
    print(f"Value {args.index} = {value:+.3f}  x {args.scale:g}  -> {args.wheel} wheel speed {speed:+d} "
          f"(cap {args.cap}){'' if abs(speed) >= config.MOTOR_MIN_SPEED else '  (below 15: may be too slow to turn)'}")
    if args.dry:
        print("--dry: not connecting to the Pi.")
        return 0
    if speed == 0:
        print("Speed 0: nothing to run.")
        return 0

    settings = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
                "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER,
                "arm_speed": 25, "grip_speed": 25, "reverse_delay": 0, "state_hz": 10}
    code = (ROOT / "pi" / "gamepad_server.py").read_text()
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

        def wheel_state() -> str:
            for line in stdout:
                if line.startswith("state "):
                    s = json.loads(line[6:])
                    if port in s:
                        return f"speed {s[port][0]:+4d}  angle {s[port][1]:+6d}"
            return "?"

        drive = [0, 0]
        drive[0 if args.wheel == "left" else 1] = sign * speed  # raw motor speed
        try:
            print(f"Before:  {wheel_state()}")
            stdin.write(json.dumps({"drive": drive}) + "\n")
            stdin.flush()
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                print(f"Running: {wheel_state()}")
            stdin.write(json.dumps({"drive": [0, 0]}) + "\n")
            stdin.flush()
            time.sleep(0.3)
            print(f"Stopped: {wheel_state()}")
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            stdin.channel.shutdown_write()  # the Pi script stops every motor when stdin closes
    return 0


if __name__ == "__main__":
    sys.exit(main())
