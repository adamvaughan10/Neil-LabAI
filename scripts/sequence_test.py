"""
Sequence test. THIS MOVES THE ROBOT: keep it lifted, or give it room to drive.

    1. drive forward for 0.5 s
    2. drive backward for 0.5 s
    3. raise the arm 30° and lower it back

    python scripts/sequence_test.py
    python scripts/sequence_test.py --drive-seconds 1 --drive-speed 50 --arm-degrees 20

Prints how far each motor turned in each step and saves
logs/sequence_test_<date>_<time>/info.json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402

TOLERANCE_ARM_DEG = 8


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drive-seconds", type=float, default=config.DRIVE_TEST_SECONDS)
    ap.add_argument("--drive-speed", type=int, default=config.DRIVE_TEST_SPEED)
    ap.add_argument("--arm-degrees", type=int, default=config.ARM_TEST_DEGREES)
    ap.add_argument("--arm-speed", type=int, default=config.ARM_TEST_SPEED)
    args = ap.parse_args()

    print(f"forward {args.drive_seconds:g} s, backward {args.drive_seconds:g} s at speed {args.drive_speed}; "
          f"arm up {args.arm_degrees}° and down at speed {args.arm_speed} ...")
    with RPiClient() as pi:
        r = hardware.drive_and_arm_sequence(args.drive_seconds, args.drive_speed,
                                            args.arm_degrees, args.arm_speed, client=pi)

    steps = r["steps"]
    # Report wheel turns as forward-positive, arm as up-positive.
    lsign, rsign, up = config.LEFT_WHEEL_SIGN_FORWARD, config.RIGHT_WHEEL_SIGN_FORWARD, -config.ARM_MOTOR_SIGN_DOWN
    ok = True
    for prev, cur in zip(steps, steps[1:]):
        dl = (cur["left"] - prev["left"]) * lsign
        dr = (cur["right"] - prev["right"]) * rsign
        da = (cur["arm"] - prev["arm"]) * up
        if cur["step"] in ("forward", "backward"):
            want = 1 if cur["step"] == "forward" else -1
            good = dl * want > 0 and dr * want > 0
            print(f"  {cur['step']:<9} left wheel {dl:+5d}°  right wheel {dr:+5d}°  -> {'OK' if good else 'CHECK'}")
        else:
            want = args.arm_degrees * (1 if cur["step"] == "arm_up" else -1)
            good = abs(da - want) <= TOLERANCE_ARM_DEG
            print(f"  {cur['step']:<9} arm {da:+4d}° (asked {want:+d}°)  -> {'OK' if good else 'CHECK'}")
        ok &= good
    net_arm = (steps[-1]["arm"] - steps[0]["arm"]) * up
    print(f"  arm ended {net_arm:+d}° from where it started")

    out_dir = config.LOGS_DIR / f"sequence_test_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True)
    (out_dir / "info.json").write_text(json.dumps({"args": vars(args), "ok": ok, **r}, indent=2))
    print(f"Saved to {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
