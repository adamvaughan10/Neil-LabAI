"""
Stream the Pi camera and the external camera together. Nothing moves.

    python scripts/stream_cameras.py                 # live window, both cameras side by side
    python scripts/stream_cameras.py --record 10     # no window: record both for 10 s, then save
    python scripts/stream_cameras.py --no-external   # Pi camera only (or --no-pi)

In the live window:  r = start/stop recording   s = snapshot   q or Esc = quit

Recordings go to logs/streams_<date>_<time>/:
    pi/        video.mp4 + frames/   (Pi camera)
    external/  video.mp4 + frames/   (external camera)
    combined.mp4                     both side by side, lined up by arrival time
    info.json                        settings, frame counts, fps, per-frame timestamps
"""
import argparse
import bisect
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config  # noqa: E402
from neil_robot.streams import ExternalCameraStream, MjpegStream, PiCameraStream  # noqa: E402
from neil_robot.video import save_frames  # noqa: E402

PANEL_HEIGHT = 480
COMBINED_FPS = 15


def panel(stream: MjpegStream, frame, label: str, now: float) -> np.ndarray:
    """One camera's image scaled to PANEL_HEIGHT, with its name, fps and age written on it."""
    if frame is None:
        img = np.zeros((PANEL_HEIGHT, 640, 3), np.uint8)
    else:
        img = frame.decode(stream.rotation)
        img = cv2.resize(img, (round(img.shape[1] * PANEL_HEIGHT / img.shape[0]), PANEL_HEIGHT))
    text = label if frame is None else f"{label}  {now - frame.ts:4.2f}s old"
    if stream.error:
        text = f"{label}: {stream.error}"[:60]
    cv2.putText(img, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(img, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return img


def side_by_side(images: list[np.ndarray]) -> np.ndarray:
    return np.hstack(images) if len(images) > 1 else images[0]


def save_recording(streams: dict, recordings: dict, t0: float, t1: float) -> Path:
    out_dir = config.LOGS_DIR / f"streams_{time.strftime('%Y%m%d_%H%M%S', time.localtime(t0))}"
    out_dir.mkdir(parents=True)
    info = {"started": t0, "duration_s": round(t1 - t0, 3), "cameras": {}}
    for name, frames in recordings.items():
        stream = streams[name]
        cam = {"url": stream.url, "rotation": stream.rotation, "frames": len(frames)}
        if frames:
            cam.update(save_frames([f.jpeg for f in frames], out_dir / name, t1 - t0, stream.rotation))
            cam["timestamps"] = [round(f.ts - t0, 4) for f in frames]
        info["cameras"][name] = cam

    # Combined video: at each tick, show each camera's newest frame that had arrived by then.
    with_frames = {n: f for n, f in recordings.items() if f}
    if with_frames:
        times = {n: [f.ts for f in fr] for n, fr in with_frames.items()}
        size = None
        writer = None
        for k in range(int((t1 - t0) * COMBINED_FPS)):
            t = t0 + k / COMBINED_FPS
            tiles = []
            for name, frames in with_frames.items():
                i = max(bisect.bisect_right(times[name], t) - 1, 0)
                tiles.append(panel(streams[name], frames[i], name, t))
            img = side_by_side(tiles)
            if writer is None:
                size = (img.shape[1], img.shape[0])
                writer = cv2.VideoWriter(str(out_dir / "combined.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                         COMBINED_FPS, size)
            writer.write(img if (img.shape[1], img.shape[0]) == size else cv2.resize(img, size))
        if writer:
            writer.release()
    (out_dir / "info.json").write_text(json.dumps(info, indent=2))
    return out_dir


def summary(streams: dict, recordings: dict, duration: float) -> str:
    return ", ".join(f"{n} {len(recordings[n])} frames ({len(recordings[n]) / duration:.1f} fps)" for n in streams)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", type=float, metavar="SECONDS", help="record for SECONDS without a window, then save")
    ap.add_argument("--no-pi", action="store_true")
    ap.add_argument("--no-external", action="store_true")
    ap.add_argument("--external-url", default=config.EXTERNAL_CAMERA_URL)
    ap.add_argument("--external-rotation", type=int, choices=(0, 90, 180, 270), default=config.EXTERNAL_CAMERA_ROTATION)
    args = ap.parse_args()

    streams: dict[str, MjpegStream] = {}
    if not args.no_pi:
        streams["pi"] = PiCameraStream()
    if not args.no_external:
        streams["external"] = ExternalCameraStream(args.external_url, args.external_rotation)
    if not streams:
        ap.error("nothing to stream")

    started = []
    try:
        for name, s in streams.items():
            print(f"Connecting to {name} camera ({s.url}) ...")
            try:
                s.start()
                started.append(s)
            except Exception as exc:  # noqa: BLE001
                print(f"  {name} camera failed: {exc}")
                return 1
        print("Streaming.")

        if args.record:
            for s in streams.values():
                s.start_recording()
            t0 = time.time()
            time.sleep(args.record)
            t1 = time.time()
            recordings = {n: s.stop_recording() for n, s in streams.items()}
            out = save_recording(streams, recordings, t0, t1)
            print(f"Recorded {args.record:g} s: {summary(streams, recordings, t1 - t0)}\nSaved to {out}")
            return 0 if all(recordings.values()) else 1

        window = "Neil-LabAI cameras  (r: record, s: snapshot, q: quit)"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        rec_t0 = None
        while True:
            now = time.time()
            img = side_by_side([panel(s, s.latest(), n, now) for n, s in streams.items()])
            if rec_t0 is not None:
                cv2.circle(img, (img.shape[1] - 30, 30), 12, (0, 0, 255), -1)
                cv2.putText(img, f"REC {now - rec_t0:4.1f}s", (img.shape[1] - 170, 38),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow(window, img)
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("s"):
                config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
                path = config.LOGS_DIR / f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(str(path), img)
                print(f"Snapshot: {path}")
            if key == ord("r"):
                if rec_t0 is None:
                    for s in streams.values():
                        s.start_recording()
                    rec_t0 = now
                    print("Recording ...")
                else:
                    recordings = {n: s.stop_recording() for n, s in streams.items()}
                    out = save_recording(streams, recordings, rec_t0, now)
                    print(f"Saved {summary(streams, recordings, now - rec_t0)} to {out}")
                    rec_t0 = None
        cv2.destroyAllWindows()
        return 0
    finally:
        for s in started:
            s.stop()


if __name__ == "__main__":
    sys.exit(main())
