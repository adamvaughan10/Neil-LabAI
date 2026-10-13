"""
Motor test: turns each motor a small amount and back, and reports encoder deltas.

THIS MOVES THE ROBOT. Put it on a stand (wheels off the table) or give it room.

    python scripts/motor_test.py                     # every port, asks before each
    python scripts/motor_test.py --ports A           # one port
    python scripts/motor_test.py --degrees 45 --speed 20
    python scripts/motor_test.py --yes               # don't ask before each port

A motor passes if it moved roughly the requested amount (and back).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient, RPiError  # noqa: E402

ROLE = {
    config.PORT_LEFT_WHEEL: "left wheel",
    config.PORT_RIGHT_WHEEL: "right wheel",
    config.PORT_GRIPPER: "gripper",
    config.PORT_ARM: "arm",
}
TOLERANCE_DEG = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ports", default="".join(config.PORTS), help="e.g. AB or C (default: all)")
    ap.add_argument("--degrees", type=int, default=config.MOTOR_TEST_DEGREES)
    ap.add_argument("--speed", type=int, default=config.MOTOR_TEST_SPEED)
    ap.add_argument("--no-return", action="store_true", help="don't move back to the start")
    ap.add_argument("--yes", action="store_true", help="don't ask before each port")
    args = ap.parse_args()

    with RPiClient() as pi:
        status = hardware.hat_status(pi)
        print(f"Build HAT input: {status['vin']:.1f} V")
        if status["vin"] < 7.0:
            print("Motors need the 8 V barrel-jack supply. Plug it in and retry.")
            return 1

        failures = 0
        for port in args.ports.upper():
            dev = status["ports"].get(port, {})
            label = f"port {port} ({ROLE.get(port, '?')})"
            if "position" not in dev:
                print(f"- {label}: no motor connected, skipped")
                continue
            if not args.yes and input(f"Move {label} by {args.degrees}° at speed {args.speed}? [y/N] ").lower() != "y":
                print(f"- {label}: skipped")
                continue
            try:
                r = hardware.move_motor(port, args.degrees, args.speed, not args.no_return, client=pi)
            except RPiError as exc:
                failures += 1
                print(f"- {label}: FAILED  {str(exc).splitlines()[0]}")
                continue
            ok = abs(r["moved"] - args.degrees) <= TOLERANCE_DEG
            msg = f"moved {r['moved']:+d}° (asked {args.degrees:+d}°)"
            if r["returned"] is not None:
                ok &= abs(r["returned"] + args.degrees) <= TOLERANCE_DEG
                msg += f", returned {r['returned']:+d}°, ended {r['after_return'] - r['start']:+d}° from start"
            failures += not ok
            print(f"- {label}: {'OK  ' if ok else 'CHECK'} {msg}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
