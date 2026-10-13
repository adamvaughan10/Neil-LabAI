"""
Synced recorder: samples every source at one fixed rate and writes each step to disk as it happens.

    rec = SyncRecorder({"pi": pi_stream, "external": ext_stream}, fps=15)
    rec.start(); ...; summary = rec.stop()

At every tick (t0 + k / fps on the high-resolution clock) it takes the newest
frame from each camera and writes:

    <out_dir>/
      pi/000000.jpg, external/000000.jpg, ...   one image per camera per step
      steps.jsonl                                one JSON line per step (below)
      info.json                                  settings + quality summary (on stop)
      pi.mp4, external.mp4, combined.mp4         made on stop, from the saved images

A steps.jsonl line:

    {"step": 12, "t": 1760356000.812, "t_rel": 0.8,
     "pi":       {"file": "pi/000012.jpg", "frame": 431, "ts": ..., "age_ms": 18.2, "new": true},
     "external": {"file": "external/000012.jpg", "frame": 377, "ts": ..., "age_ms": 30.1, "new": true},
     "skew_ms": 11.9}

"frame" is the camera's own frame counter, "new" is false when the camera sent
nothing since the previous step (the image repeats), "age_ms" is how old the
image was at the tick, and "skew_ms" is the largest time gap between the
cameras' images in that step. Every step has every camera's image, so a
loader can read the steps in order without gaps.

Extra per-step data (e.g. motor encoders) can be added with *extras*:
name -> callable(t) returning a JSON-serialisable dict, stored under that name.
Extras must return immediately (read a cached value; never block on I/O).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from neil_robot import clock, config
from neil_robot.streams import MjpegStream
from neil_robot.video import rotate

PANEL_HEIGHT = 480


class SyncRecorder:
    def __init__(
        self,
        cameras: dict[str, MjpegStream],
        fps: float = config.RECORD_FPS,
        out_dir: Path | None = None,
        extras: dict[str, Callable[[float], dict]] | None = None,
        make_videos: bool = True,
    ):
        self.cameras = cameras
        self.fps = fps
        self.out_dir = out_dir or config.LOGS_DIR / f"session_{time.strftime('%Y%m%d_%H%M%S')}"
        self.extras = extras or {}
        self.make_videos = make_videos
        self.steps = 0
        self.t0: float | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._ticker: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._stats = {n: {"repeated": 0, "missing": 0, "age_ms": []} for n in cameras}
        self._skews: list[float] = []
        self._late_ticks = 0
        self.writer_error: Exception | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> "SyncRecorder":
        for name in self.cameras:
            (self.out_dir / name).mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._writer = threading.Thread(target=self._write_loop, name="recorder-writer", daemon=True)
        self._writer.start()
        self._ticker = threading.Thread(target=self._tick_loop, name="recorder-ticker", daemon=True)
        self._ticker.start()
        while self.t0 is None:
            time.sleep(0.001)
        return self

    def stop(self) -> dict:
        """Stop ticking, finish writing, and save info.json (and videos). Returns the summary."""
        self._stop.set()
        self._ticker.join()
        self._queue.put(None)
        self._writer.join()
        summary = self._summary()
        (self.out_dir / "info.json").write_text(json.dumps(summary, indent=2))
        if self.make_videos and self.steps:
            self._write_videos()
        return summary

    @property
    def elapsed(self) -> float:
        return 0.0 if self.t0 is None else clock.now() - self.t0

    # ── ticking ───────────────────────────────────────────────────────────────

    def _tick_loop(self) -> None:
        period = 1.0 / self.fps
        # Start on a clean tick a little ahead, so step 0 isn't late.
        self.t0 = clock.now() + 0.05
        last_index = {n: None for n in self.cameras}
        k = 0
        while not self._stop.is_set():
            t = self.t0 + k * period
            clock.sleep_until(t)
            if clock.now() - t > period / 2:
                self._late_ticks += 1
            row = {"step": k, "t": round(t, 6), "t_rel": round(t - self.t0, 6)}
            files = {}
            stamps = []
            for name, cam in self.cameras.items():
                frame = cam.latest()
                if frame is None:
                    row[name] = None
                    self._stats[name]["missing"] += 1
                    continue
                new = frame.index != last_index[name]
                last_index[name] = frame.index
                age = (t - frame.ts) * 1000
                path = f"{name}/{k:06d}.jpg"
                row[name] = {"file": path, "frame": frame.index, "ts": round(frame.ts, 6),
                             "age_ms": round(age, 2), "new": new}
                files[path] = frame.jpeg
                stamps.append(frame.ts)
                self._stats[name]["repeated"] += not new and k > 0
                self._stats[name]["age_ms"].append(age)
            if len(stamps) > 1:
                skew = (max(stamps) - min(stamps)) * 1000
                row["skew_ms"] = round(skew, 2)
                self._skews.append(skew)
            for name, fn in self.extras.items():
                try:
                    row[name] = fn(t)
                except Exception as exc:  # noqa: BLE001
                    row[name] = {"error": repr(exc)}
            self._queue.put((row, files))
            self.steps = k = k + 1

    # ── writing ───────────────────────────────────────────────────────────────

    def _write_loop(self) -> None:
        with open(self.out_dir / "steps.jsonl", "w", encoding="utf-8") as log:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                row, files = item
                try:
                    for path, data in files.items():
                        (self.out_dir / path).write_bytes(data)
                    log.write(json.dumps(row) + "\n")
                    log.flush()
                except Exception as exc:  # noqa: BLE001
                    self.writer_error = exc

    # ── summary and videos ────────────────────────────────────────────────────

    def _summary(self) -> dict:
        def pct(v, q):
            return round(float(np.percentile(v, q)), 1) if len(v) else None

        cams = {}
        for name, cam in self.cameras.items():
            st = self._stats[name]
            cams[name] = {
                "url": cam.url, "rotation": cam.rotation, "latency_s": cam.latency_s,
                "repeated_steps": st["repeated"], "missing_steps": st["missing"],
                "repeated_pct": round(100 * st["repeated"] / max(self.steps - 1, 1), 2),
                "age_ms": {"median": pct(st["age_ms"], 50), "p95": pct(st["age_ms"], 95)},
            }
        return {
            "fps": self.fps, "steps": self.steps, "duration_s": round(self.steps / self.fps, 3),
            "t0": self.t0, "late_ticks": self._late_ticks, "cameras": cams,
            "skew_ms": {"median": pct(self._skews, 50), "p95": pct(self._skews, 95),
                        "max": round(max(self._skews), 1) if self._skews else None},
            "writer_error": repr(self.writer_error) if self.writer_error else None,
        }

    def _write_videos(self) -> None:
        names = list(self.cameras)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writers: dict[str, cv2.VideoWriter] = {}
        last: dict[str, np.ndarray] = {}
        sizes: dict[str, tuple[int, int]] = {}
        for line in (self.out_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            tiles = []
            for name in names:
                if row.get(name):
                    # imdecode, not imread: OpenCV can't open non-ASCII paths on Windows.
                    data = (self.out_dir / row[name]["file"]).read_bytes()
                    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    last[name] = rotate(img, self.cameras[name].rotation)
                img = last.get(name)
                if img is None:
                    img = np.zeros((PANEL_HEIGHT, 640, 3), np.uint8)
                    last[name] = img
                if name not in writers:
                    size = (img.shape[1], img.shape[0])
                    writers[name] = cv2.VideoWriter(str(self.out_dir / f"{name}.mp4"), fourcc, self.fps, size)
                    sizes[name] = size
                writers[name].write(img if (img.shape[1], img.shape[0]) == sizes[name] else cv2.resize(img, sizes[name]))
                # No text overlays: these videos may be used as model input.
                tiles.append(cv2.resize(img, (round(img.shape[1] * PANEL_HEIGHT / img.shape[0]), PANEL_HEIGHT)))
            combined = np.hstack(tiles)
            if "combined" not in writers:
                sizes["combined"] = (combined.shape[1], combined.shape[0])
                writers["combined"] = cv2.VideoWriter(str(self.out_dir / "combined.mp4"), fourcc, self.fps,
                                                      sizes["combined"])
            if (combined.shape[1], combined.shape[0]) != sizes["combined"]:
                combined = cv2.resize(combined, sizes["combined"])
            writers["combined"].write(combined)
        for w in writers.values():
            w.release()
