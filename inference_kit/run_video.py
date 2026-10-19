"""The video of a run, for people to watch.

The model works at FPS, the 10 frames per second of the training data, which is too choppy to
watch. RunVideo records the cameras at RUN_VIDEO_FPS (30) in its own threads, apart from the
model: front.mp4, top.mp4 and side_by_side.mp4, plus video.json. The model never sees them.
"""
import json
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# The front camera sends 30 frames per second. The iPhone sends about 26, so about 1 in 8
# of its frames shows twice in the video.
RUN_VIDEO_FPS = 30
HEIGHT = 480  # side_by_side.mp4 scales both views to this height


class RunVideo:
    """cams: {"front": Camera, "top": Camera} from neil_io. Every 1/fps s one thread takes the
    newest image of each camera (the last one again if the camera sent nothing new, so the
    video keeps real time). Another thread encodes, so slow encoding never delays an image."""

    def __init__(self, cams, out_dir, fps=RUN_VIDEO_FPS):
        self.cams, self.out_dir, self.fps = cams, Path(out_dir), fps
        self.frames, self.repeated, self.codec, self.error = 0, dict.fromkeys(cams, 0), None, None
        self.queue, self.stopping = queue.Queue(), threading.Event()
        self.threads = [threading.Thread(target=f, daemon=True) for f in (self._take, self._encode)]

    def start(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for cam in self.cams.values():
            cam.read()  # waits for the camera's first image
        for t in self.threads:
            t.start()
        return self

    def stop(self):
        """Finishes the videos. Returns what it writes to video.json."""
        self.stopping.set()
        for t in self.threads:
            t.join()
        info = {"fps": self.fps, "frames": self.frames, "codec": self.codec,
                "repeated_pct": {n: round(100 * r / max(self.frames - 1, 1), 1) for n, r in self.repeated.items()},
                "error": repr(self.error) if self.error else None}
        (self.out_dir / "video.json").write_text(json.dumps(info, indent=2))
        return info

    def _take(self):
        t0, last = time.perf_counter(), {}
        while not self.stopping.is_set():
            imgs = {name: cam.frame for name, cam in self.cams.items()}  # Camera makes a new array per image
            for name, img in imgs.items():
                self.repeated[name] += img is last.get(name)
            last = imgs
            self.queue.put(imgs)
            self.frames += 1
            time.sleep(max(0.0, t0 + self.frames / self.fps - time.perf_counter()))
        self.queue.put(None)

    def _encode(self):
        writers = {}
        while (imgs := self.queue.get()) is not None:
            if self.error:
                continue  # keep emptying the queue, so it doesn't fill the memory
            try:
                tiles = []
                for name, img in imgs.items():
                    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    self._write(writers, name, bgr)
                    width = 2 * round(bgr.shape[1] * HEIGHT / bgr.shape[0] / 2)  # even: H.264 needs it
                    tiles.append(cv2.resize(bgr, (width, HEIGHT)))
                self._write(writers, "side_by_side", np.hstack(tiles))
            except Exception as e:  # noqa: BLE001
                self.error = e
                print(f"\nVideo of the run stopped: {e}")
        for w in writers.values():
            w.release()

    def _write(self, writers, name, img):
        if name not in writers:
            writers[name] = self._open(self.out_dir / f"{name}.mp4", (img.shape[1], img.shape[0]))
        writers[name].write(img)

    def _open(self, path, size):
        """H.264 (plays in browsers and chat apps) if this OpenCV has it, else MPEG-4."""
        for codec in ([self.codec] if self.codec else ["avc1", "mp4v"]):
            level = cv2.utils.logging.getLogLevel()
            if codec == "avc1":  # no H.264 is not an error here: mp4v comes next
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
            try:
                w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), self.fps, size)
            finally:
                cv2.utils.logging.setLogLevel(level)
            if w.isOpened():
                self.codec = codec
                return w
        raise RuntimeError(f"cannot write {path.name}")
