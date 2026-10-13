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

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient, RPiError  # noqa: E402


def split_mjpeg(data: bytes) -> list[bytes]:
    """Split back-to-back JPEGs (MJPEG stream) into individual JPEG files."""
    frames, start = [], data.find(b"\xff\xd8")
    while start != -1:
        end = data.find(b"\xff\xd9\xff\xd8", start)
        if end == -1:
            frames.append(data[start:])
            break
        frames.append(data[start:end + 2])
        start = end + 2
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--width", type=int, default=config.VIDEO_WIDTH)
    ap.add_argument("--height", type=int, default=config.VIDEO_HEIGHT)
    ap.add_argument("--fps", type=int, default=config.VIDEO_FPS)
    args = ap.parse_args()

    out_dir = config.LOGS_DIR / f"recording_{time.strftime('%Y%m%d_%H%M%S')}"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True)
    raw_path = out_dir / "raw.mjpeg"

    print(f"Recording {args.seconds:g} s from {config.RPI_USER}@{config.RPI_HOST} "
          f"({args.width}x{args.height} @ {args.fps} fps) ...")
    try:
        with RPiClient() as pi:
            info = hardware.record_video(raw_path, args.seconds, args.width, args.height, args.fps, client=pi)
    except RPiError as exc:
        print(f"Recording failed: {exc}")
        return 1

    jpegs = split_mjpeg(raw_path.read_bytes())
    if not jpegs:
        print(f"No frames in the recording ({raw_path})")
        return 1
    for i, jpg in enumerate(jpegs):
        (frames_dir / f"frame_{i:04d}.jpg").write_bytes(jpg)

    # Play back at the rate the camera actually delivered, so the clip lasts as long as the recording did.
    measured_fps = len(jpegs) / info["elapsed_s"]
    first = cv2.imdecode(np.frombuffer(jpegs[0], np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    writer = cv2.VideoWriter(str(out_dir / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), measured_fps, (w, h))
    for jpg in jpegs:
        writer.write(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
    writer.release()
    raw_path.unlink()

    meta = {
        "camera": info["camera"], "host": config.RPI_HOST,
        "requested": {"seconds": args.seconds, "width": args.width, "height": args.height, "fps": args.fps},
        "frames": len(jpegs), "size": [w, h],
        "recorded_s": round(info["elapsed_s"], 3), "measured_fps": round(measured_fps, 2),
    }
    (out_dir / "info.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved {len(jpegs)} frames ({w}x{h}, {measured_fps:.1f} fps, {info['camera']}) to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
