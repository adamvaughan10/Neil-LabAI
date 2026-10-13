"""
Arm test: lowers the arm (port D) and raises it back while the Pi Camera records.

THIS MOVES THE ARM. Keep hands clear; ideally the robot is lifted off the table.

    python scripts/arm_test.py                       # lower 30° and back at speed 10
    python scripts/arm_test.py --degrees 45 --speed 8
    python scripts/arm_test.py --no-video

Saves logs/arm_test_<date>_<time>/ with video.mp4, frames/, and info.json
(encoder positions with timestamps, measured from when recording started).
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402
from neil_robot.video import save_clip  # noqa: E402

CAMERA_LEAD_S = 1.5   # start moving once the camera is rolling
CAMERA_TAIL_S = 2.0   # keep recording after the motion
TOLERANCE_DEG = 8


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--degrees", type=int, default=config.ARM_TEST_DEGREES)
    ap.add_argument("--speed", type=int, default=config.ARM_TEST_SPEED)
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()

    out_dir = config.LOGS_DIR / f"arm_test_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True)
    raw_path = out_dir / "raw.mjpeg"
    results: dict = {}

    def record():
        # Long enough for both legs at slow arm speed, plus the lead and tail.
        seconds = CAMERA_LEAD_S + 4.0 + CAMERA_TAIL_S
        try:
            with RPiClient() as cam:
                results["video"] = hardware.record_video(raw_path, seconds, client=cam)
        except Exception as exc:  # noqa: BLE001
            results["video_error"] = exc

    recorder = None
    if not args.no_video:
        recorder = threading.Thread(target=record)
        recorder.start()

    print(f"Lowering the arm {args.degrees}° and raising it back at speed {args.speed} ...")
    with RPiClient() as pi:
        motion = hardware.arm_down_up(args.degrees, args.speed,
                                      delay_s=0 if args.no_video else CAMERA_LEAD_S, client=pi)
    if recorder:
        recorder.join()

    ok = abs(motion["lowered_deg"] - args.degrees) <= TOLERANCE_DEG and abs(motion["net_deg_from_start"]) <= TOLERANCE_DEG
    print(f"  lowered {motion['lowered_deg']:+d}° (asked {args.degrees}°), raised {motion['raised_deg']:+d}°, "
          f"ended {motion['net_deg_from_start']:+d}° from start  ->  {'OK' if ok else 'CHECK'}")
    for s in motion["samples"]:
        print(f"  t={s['t']:5.2f}s  {s['phase']:<8} position {s['pos']}°")

    meta = {"degrees": args.degrees, "speed": args.speed, "ok": ok, "motion": motion}
    if "video" in results:
        meta["clip"] = save_clip(raw_path, out_dir, results["video"]["elapsed_s"])
        print(f"  video: {meta['clip']['frames']} frames -> {out_dir / 'video.mp4'}")
    elif "video_error" in results:
        meta["video_error"] = str(results["video_error"])
        print(f"  video failed: {str(results['video_error']).splitlines()[0]}")
    (out_dir / "info.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved to {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
