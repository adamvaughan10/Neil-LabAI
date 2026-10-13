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


_ROTATE = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def rotate(img: np.ndarray, degrees_cw: int) -> np.ndarray:
    return cv2.rotate(img, _ROTATE[degrees_cw]) if degrees_cw in _ROTATE else img


def save_frames(jpegs: list[bytes], out_dir: Path, elapsed_s: float, rotation: int = 0) -> dict:
    """Write out_dir/frames/frame_NNNN.jpg (as received) and out_dir/video.mp4 (rotated
    clockwise by *rotation*). Returns {"frames", "size", "measured_fps"}."""
    if not jpegs:
        raise RuntimeError("no frames to save")
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i, jpg in enumerate(jpegs):
        (frames_dir / f"frame_{i:04d}.jpg").write_bytes(jpg)

    def decode(jpg):
        return rotate(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR), rotation)

    # Play back at the rate the camera actually delivered, so the clip lasts as long as the recording did.
    fps = len(jpegs) / elapsed_s if elapsed_s > 0 else 1.0
    h, w = decode(jpegs[0]).shape[:2]
    writer = cv2.VideoWriter(str(out_dir / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for jpg in jpegs:
        img = decode(jpg)
        writer.write(img if img.shape[:2] == (h, w) else cv2.resize(img, (w, h)))
    writer.release()
    return {"frames": len(jpegs), "size": [w, h], "measured_fps": round(fps, 2)}


def save_clip(raw_path: Path, out_dir: Path, elapsed_s: float) -> dict:
    """save_frames() for a raw MJPEG file recorded on the Pi; deletes the file afterwards."""
    jpegs = split_mjpeg(raw_path.read_bytes())
    if not jpegs:
        raise RuntimeError(f"no frames in the recording ({raw_path})")
    result = save_frames(jpegs, out_dir, elapsed_s)
    raw_path.unlink()
    return result
