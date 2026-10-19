"""
The videos of a policy run, for people to watch: the cameras at a smooth rate (RUN_VIDEO_FPS,
30 fps), apart from the rate the policy steps at (10 fps for the pick_cup model, too choppy).

    video = RunVideo({"pi": pi_stream, "external": ext_stream}, out_dir).start()
    ...; summary = video.stop()

writes into out_dir:

    pi.mp4, external.mp4, combined.mp4   combined.mp4: both cameras side by side
    video.json                           rate, codec, and how many frames each camera repeated

At every tick (t0 + k / fps) it takes the newest frame from each camera, like the recorder
does, so the videos keep real time: a camera that sent nothing new since the last tick repeats
its frame. A second thread decodes and encodes, so a slow encoder never delays a tick.
The policy's inputs are the recorder's per-step images; nothing here is model input. Use it
with a recorder that doesn't make videos of its own (make_videos=False): same file names.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from neil_robot import clock, config
from neil_robot.streams import Frame, MjpegStream
from neil_robot.video import rotate

PANEL_HEIGHT = 480


class RunVideo:
    def __init__(self, cameras: dict[str, MjpegStream], out_dir: Path, fps: float = config.RUN_VIDEO_FPS):
        self.cameras = cameras
        self.out_dir = Path(out_dir)
        self.fps = fps
        self.frames = 0
        self.t0: float | None = None
        self.codec: str | None = None
        self.error: Exception | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._ticker: threading.Thread | None = None
        self._encoder: threading.Thread | None = None
        self._repeated = dict.fromkeys(cameras, 0)
        self._late_ticks = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> "RunVideo":
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._encoder = threading.Thread(target=self._encode_loop, name="video-encoder", daemon=True)
        self._encoder.start()
        self._ticker = threading.Thread(target=self._tick_loop, name="video-ticker", daemon=True)
        self._ticker.start()
        while self.t0 is None:
            time.sleep(0.001)
        return self

    def stop(self) -> dict:
        """Stop ticking, finish the videos, and save video.json. Returns the summary."""
        self._stop.set()
        self._ticker.join()
        self._queue.put(None)
        self._encoder.join()
        summary = {
            "fps": self.fps, "frames": self.frames, "duration_s": round(self.frames / self.fps, 3),
            "late_ticks": self._late_ticks, "codec": self.codec,
            "cameras": {n: {"repeated_frames": r, "repeated_pct": round(100 * r / max(self.frames - 1, 1), 2)}
                        for n, r in self._repeated.items()},
            "error": repr(self.error) if self.error else None,
        }
        (self.out_dir / "video.json").write_text(json.dumps(summary, indent=2))
        return summary

    # ── ticking ───────────────────────────────────────────────────────────────

    def _tick_loop(self) -> None:
        period = 1.0 / self.fps
        self.t0 = clock.now() + 0.05
        last_index = {n: None for n in self.cameras}
        k = 0
        while not self._stop.is_set():
            t = self.t0 + k * period
            # A plain sleep, not clock.sleep_until's spin: a millisecond off doesn't show in a video.
            time.sleep(max(0.0, t - clock.now()))
            if clock.now() - t > period / 2:
                self._late_ticks += 1
            frames = {name: cam.latest() for name, cam in self.cameras.items()}
            for name, frame in frames.items():
                if frame is not None:
                    self._repeated[name] += k > 0 and frame.index == last_index[name]
                    last_index[name] = frame.index
            self._queue.put(frames)
            self.frames = k = k + 1

    # ── encoding ──────────────────────────────────────────────────────────────

    def _encode_loop(self) -> None:
        writers: dict[str, tuple[cv2.VideoWriter, tuple[int, int]]] = {}
        decoded: dict[str, tuple[int, np.ndarray]] = {}  # camera -> (frame index, image)
        while (frames := self._queue.get()) is not None:
            if self.error:
                continue  # keep draining, so the queue doesn't grow for the rest of the run
            try:
                self._encode(frames, writers, decoded)
            except Exception as exc:  # noqa: BLE001
                self.error = exc
        for w, _ in writers.values():
            w.release()

    def _encode(self, frames: dict[str, Frame | None], writers: dict, decoded: dict) -> None:
        tiles = []
        for name, frame in frames.items():
            if frame is not None and decoded.get(name, (None,))[0] != frame.index:
                img = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:  # else a damaged JPEG: keep showing the last good frame
                    decoded[name] = (frame.index, rotate(img, self.cameras[name].rotation))
            img = decoded[name][1] if name in decoded else np.zeros((PANEL_HEIGHT, 640, 3), np.uint8)
            self._write(writers, name, img)
            width = 2 * round(img.shape[1] * PANEL_HEIGHT / img.shape[0] / 2)  # even: H.264 needs it
            tiles.append(cv2.resize(img, (width, PANEL_HEIGHT)))
        self._write(writers, "combined", np.hstack(tiles))

    def _write(self, writers: dict, name: str, img: np.ndarray) -> None:
        if name not in writers:
            size = (img.shape[1], img.shape[0])
            writers[name] = (self._open(self.out_dir / f"{name}.mp4", size), size)
        w, size = writers[name]
        w.write(img if (img.shape[1], img.shape[0]) == size else cv2.resize(img, size))

    def _open(self, path: Path, size: tuple[int, int]) -> cv2.VideoWriter:
        """H.264 (plays in browsers and chat apps) if this OpenCV build has it, else MPEG-4.
        The first video picks the codec, so a build without H.264 is tried only once."""
        for codec in ([self.codec] if self.codec else ["avc1", "mp4v"]):
            level = cv2.utils.logging.getLogLevel()
            if codec == "avc1":  # no H.264 isn't an error here: mp4v comes next
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
            try:
                w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), self.fps, size)
            finally:
                cv2.utils.logging.setLogLevel(level)
            if w.isOpened():
                self.codec = codec
                return w
        raise RuntimeError(f"can't write {path.name} with {self.codec or 'avc1 or mp4v'}")
