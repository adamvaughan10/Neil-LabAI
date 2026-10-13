"""
Record a clip from the robot's Pi Camera, starting immediately. Nothing moves.

    python scripts/record_video.py                 # 5 s at 1296x972, 30 fps
    python scripts/record_video.py --seconds 10 --fps 15
    python scripts/record_video.py --width 640 --height 480

Each run makes logs/recording_<date>_<time>/ with:
    video.mp4     the clip
    frames/       every frame as a JPEG (frame_0000.jpg, ...)
    info.json     settings, frame count, measured fps
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient, RPiError  # noqa: E402
from neil_robot.video import save_clip  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--width", type=int, default=config.VIDEO_WIDTH)
    ap.add_argument("--height", type=int, default=config.VIDEO_HEIGHT)
    ap.add_argument("--fps", type=int, default=config.VIDEO_FPS)
    ap.add_argument("--rotation", type=int, choices=(0, 180), default=config.CAMERA_ROTATION,
                    help="180 (default): fixed flip; 0: as mounted")
    args = ap.parse_args()

    out_dir = config.LOGS_DIR / f"recording_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True)
    raw_path = out_dir / "raw.mjpeg"

    print(f"Recording {args.seconds:g} s from {config.RPI_USER}@{config.RPI_HOST} "
          f"({args.width}x{args.height} @ {args.fps} fps) ...")
    try:
        with RPiClient() as pi:
            info = hardware.record_video(raw_path, args.seconds, args.width, args.height, args.fps,
                                         args.rotation, client=pi)
    except RPiError as exc:
        print(f"Recording failed: {exc}")
        return 1

    clip = save_clip(raw_path, out_dir, info["elapsed_s"])
    meta = {
        "camera": info["camera"], "host": config.RPI_HOST,
        "requested": {"seconds": args.seconds, "width": args.width, "height": args.height, "fps": args.fps,
                      "rotation": args.rotation},
        **clip, "recorded_s": round(info["elapsed_s"], 3),
    }
    (out_dir / "info.json").write_text(json.dumps(meta, indent=2))
    w, h = clip["size"]
    print(f"Saved {clip['frames']} frames ({w}x{h}, {clip['measured_fps']:.1f} fps, {info['camera']}) to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
