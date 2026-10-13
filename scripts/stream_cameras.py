"""
Stream the Pi camera and the external camera together, and record them synced. Nothing moves.

    python scripts/stream_cameras.py                 # live window, both cameras side by side
    python scripts/stream_cameras.py --record 10     # no window: record 10 s synced, then exit
    python scripts/stream_cameras.py --fps 10        # record at 10 steps per second (default 15)
    python scripts/stream_cameras.py --no-external   # Pi camera only (or --no-pi)

In the live window:  r = start/stop recording   s = snapshot   q or Esc = quit

Recording samples both cameras at a fixed rate and writes every step to disk as it
happens (see neil_robot/recorder.py), into logs/session_<date>_<time>/:
    pi/000000.jpg ...  external/000000.jpg ...   one image per camera per step
    steps.jsonl                                  one line per step: time, frames, ages, skew
    info.json                                    settings and sync quality
    pi.mp4  external.mp4  combined.mp4           made when the recording stops
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import clock, config  # noqa: E402
from neil_robot.recorder import SyncRecorder  # noqa: E402
from neil_robot.streams import ExternalCameraStream, MjpegStream, PiCameraStream  # noqa: E402

PANEL_HEIGHT = 480


def panel(stream: MjpegStream, label: str, now: float) -> np.ndarray:
    """The camera's newest image scaled to PANEL_HEIGHT, with its name and age written on it."""
    frame = stream.latest()
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


def report(summary: dict, out_dir: Path) -> str:
    cams = ", ".join(f"{n} repeated {c['repeated_pct']}% (age p95 {c['age_ms']['p95']} ms)"
                     for n, c in summary["cameras"].items())
    skew = summary["skew_ms"]
    return (f"Recorded {summary['steps']} steps at {summary['fps']:g} fps ({summary['duration_s']} s). {cams}. "
            f"Camera skew median {skew['median']} ms, p95 {skew['p95']} ms. Late ticks: {summary['late_ticks']}."
            + (f" WRITE ERROR: {summary['writer_error']}" if summary["writer_error"] else "")
            + f"\nSaved to {out_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", type=float, metavar="SECONDS", help="record for SECONDS without a window, then exit")
    ap.add_argument("--fps", type=float, default=config.RECORD_FPS, help="recording steps per second (default 15)")
    ap.add_argument("--no-videos", action="store_true", help="don't make mp4s when a recording stops")
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

    def new_recorder() -> SyncRecorder:
        return SyncRecorder(streams, fps=args.fps, make_videos=not args.no_videos)

    started = []
    recorder = None
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
            recorder = new_recorder().start()
            print(f"Recording {args.record:g} s at {args.fps:g} fps ...")
            clock.sleep_until(recorder.t0 + args.record)
            rec, recorder = recorder, None
            print("Saving ...")
            summary = rec.stop()
            print(report(summary, rec.out_dir))
            return 0 if summary["steps"] and not summary["writer_error"] else 1

        window = "Neil-LabAI cameras  (r: record, s: snapshot, q: quit)"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        while True:
            now = clock.now()
            img = np.hstack([panel(s, n, now) for n, s in streams.items()])
            if recorder is not None:
                cv2.circle(img, (img.shape[1] - 30, 30), 12, (0, 0, 255), -1)
                cv2.putText(img, f"REC {recorder.steps} steps", (img.shape[1] - 230, 38),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow(window, img)
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("s"):
                config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
                path = config.LOGS_DIR / f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}_{int(now * 1000) % 1000:03d}.jpg"
                path.write_bytes(cv2.imencode(".jpg", img)[1].tobytes())  # imwrite fails on non-ASCII paths
                print(f"Snapshot: {path}")
            if key == ord("r"):
                if recorder is None:
                    recorder = new_recorder().start()
                    print(f"Recording at {args.fps:g} fps to {recorder.out_dir} ...")
                else:
                    rec, recorder = recorder, None
                    print("Saving ...")
                    print(report(rec.stop(), rec.out_dir))
        cv2.destroyAllWindows()
        return 0
    finally:
        if recorder is not None:  # quit mid-recording: keep what was recorded
            print("Saving the recording in progress ...")
            print(report(recorder.stop(), recorder.out_dir))
        for s in started:
            s.stop()


if __name__ == "__main__":
    sys.exit(main())
