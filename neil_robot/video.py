"""Turn a raw MJPEG recording from the Pi into video.mp4 + frames/ in a log folder."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


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


def save_clip(raw_path: Path, out_dir: Path, elapsed_s: float) -> dict:
    """Write out_dir/frames/frame_NNNN.jpg and out_dir/video.mp4 from *raw_path*, then delete it.

    Returns {"frames", "size", "measured_fps"}.
    """
    jpegs = split_mjpeg(raw_path.read_bytes())
    if not jpegs:
        raise RuntimeError(f"no frames in the recording ({raw_path})")
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i, jpg in enumerate(jpegs):
        (frames_dir / f"frame_{i:04d}.jpg").write_bytes(jpg)

    # Play back at the rate the camera actually delivered, so the clip lasts as long as the recording did.
    fps = len(jpegs) / elapsed_s
    h, w = cv2.imdecode(np.frombuffer(jpegs[0], np.uint8), cv2.IMREAD_COLOR).shape[:2]
    writer = cv2.VideoWriter(str(out_dir / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for jpg in jpegs:
        writer.write(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
    writer.release()
    raw_path.unlink()
    return {"frames": len(jpegs), "size": [w, h], "measured_fps": round(fps, 2)}
