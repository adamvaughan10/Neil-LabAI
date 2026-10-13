"""
Record teleop episodes in the DATA-CONTRACT.md format, for VLA training.

Each episode is one folder:

    ep_0007/
        frames.jsonl   one line per frame at FPS: {"i", "t", "state", "action", "gamepad"}
        episode.json   {"task", "success", "frames", "driver", "date", "notes", ...}
        front.mp4      the Pi camera, frame n = line n of frames.jsonl
        top.mp4        the iPhone camera, same

Units, all in robot terms (config's mounting sign flips applied):
    state.left_speed / right_speed   measured wheel speed, -100..100, + = forward
    state.arm_pos / grip_pos         degrees since the recorder started, + = down / open
    action.left / right              commanded wheel speed, -100..100, + = forward
    action.arm / grip                the angle the last button press sent it to, same zero as state

The arm and gripper move a fixed step per button press (pi/gamepad_server.py), so
their action is the target angle, which only changes on a press. Start the recorder
with the arm fully up and the gripper fully open, so 0° is the same pose in every session.
"""
from __future__ import annotations

import base64
import json
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from neil_robot import config
from neil_robot.dashboard import PI_CAMERA_SWAP_RB, PI_CAMERA_URL, start_pi_script
from neil_robot.rpi_client import RPiClient

FPS = 10  # contract: 10 frames per second
VIDEO_SIZE = (640, 480)  # contract: every video is 640x480
STALE_S = 0.5  # a camera frame older than this counts as stale in episode.json
STATE_HZ = 20  # how often pi/gamepad_server.py reports the motors while recording

_PI_DIR = Path(__file__).resolve().parent.parent / "pi"
_ROTATE = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


class LatestFrame:
    """Keeps the newest frame of one camera (BGR, VIDEO_SIZE) from a background thread."""

    def __init__(self, name: str):
        self.name = name
        self.status = "off"
        self._frame: np.ndarray | None = None
        self._time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._pi: tuple | None = None  # (client, stdin) of our own camera process on the Pi

    def get(self) -> tuple[np.ndarray | None, float]:
        """(frame, its age in seconds)."""
        with self._lock:
            return self._frame, time.monotonic() - self._time

    def _put(self, frame: np.ndarray | None, rotation: int = 0, swap_rb: bool = False) -> None:
        if frame is None:
            return
        if rotation in _ROTATE:
            frame = cv2.rotate(frame, _ROTATE[rotation])
        if swap_rb:
            frame = frame[:, :, ::-1]
        frame = _fit(frame, VIDEO_SIZE)
        with self._lock:
            self._frame, self._time = frame, time.monotonic()
        self.status = "live"

    def _start(self, target, *args) -> None:
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    # ── sources ──────────────────────────────────────────────────────────────

    def start_mjpeg(self, url: str, rotation: int = 0, swap_rb: bool = False, retry_s: float = 3) -> "LatestFrame":
        def run():
            while not self._stop.is_set():
                self.status = f"connecting to {url}"
                cap = cv2.VideoCapture(url)
                try:
                    while cap.isOpened() and not self._stop.is_set():
                        ok, frame = cap.read()
                        if not ok:
                            break
                        self._put(frame, rotation, swap_rb)
                finally:
                    cap.release()
                self.status = f"no stream at {url}, retrying"
                self._stop.wait(retry_s)
        self._start(run)
        return self

    def start_pi_camera(self) -> "LatestFrame":
        def run():
            if PI_CAMERA_URL:
                cap = cv2.VideoCapture(PI_CAMERA_URL)
                if cap.isOpened():
                    cap.release()
                    self.start_mjpeg(PI_CAMERA_URL, 0, PI_CAMERA_SWAP_RB)
                    return
            self.status = "starting on the Pi"
            try:
                client = RPiClient()  # its own SSH connection, so video never delays motor commands
                settings = {"width": VIDEO_SIZE[0], "height": VIDEO_SIZE[1], "fps": 2 * FPS,
                            "rotation": config.CAMERA_ROTATION}
                stdin, stdout = start_pi_script(client, _PI_DIR / "camera_stream.py", settings)
                self._pi = (client, stdin)
                for line in stdout:
                    if line.startswith("jpeg "):
                        jpeg = np.frombuffer(base64.b64decode(line[5:]), np.uint8)
                        self._put(cv2.imdecode(jpeg, cv2.IMREAD_COLOR))
                self.status = "Pi camera stream ended"
            except Exception as exc:
                reason = "camera in use by another program" if "in use by another process" in str(exc) else \
                    str(exc).strip().splitlines()[-1][:120]
                self.status = f"unavailable: {reason}"
        self._start(run)
        return self

    def close(self) -> None:
        self._stop.set()
        if self._pi:
            client, stdin = self._pi
            try:
                stdin.channel.shutdown_write()
            except OSError:
                pass
            client.close()
        for t in self._threads:
            t.join(timeout=3)


def _fit(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Letterbox to size without stretching (a portrait iPhone frame gets black bars)."""
    w, h = size
    fh, fw = frame.shape[:2]
    if (fw, fh) == (w, h):
        return frame
    s = min(w / fw, h / fh)
    nw, nh = max(1, round(fw * s)), max(1, round(fh * s))
    out = np.zeros((h, w, 3), np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    out[y:y + nh, x:x + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return out


class EpisodeRecorder:
    """Samples motors, commands, gamepad and cameras at FPS while an episode is recording.

    Feed it the Pi's "state" lines with on_state(), and the driving loop's commands
    with drive() / step() / pad(). A background thread writes one frame per tick.
    """

    def __init__(self, out_dir: Path, cameras: dict[str, LatestFrame], task: str, driver: str = ""):
        self.out_dir = Path(out_dir)
        self.cameras = cameras  # contract name ("front", "top") -> feed
        self.task, self.driver = task, driver
        self._lock = threading.Lock()
        self._state: dict | None = None  # robot terms, absolute encoder degrees
        self._zero: dict[str, float] | None = None
        self._cmd = {"left": 0, "right": 0}
        self._target: dict[str, float] = {}
        self._pad: dict = {"axes": [0.0] * 4, "buttons": [0] * 12}
        self._episode: dict | None = None
        self._thread: threading.Thread | None = None

    # ── inputs ───────────────────────────────────────────────────────────────

    def on_state(self, raw: dict) -> None:
        """One "state" report from pi/gamepad_server.py: {port: [speed, position]} in motor terms."""
        if "error" in raw:  # a failed read on the Pi; keep the last good state
            return
        state = {
            "left_speed": config.LEFT_WHEEL_SIGN_FORWARD * raw[config.PORT_LEFT_WHEEL][0],
            "right_speed": config.RIGHT_WHEEL_SIGN_FORWARD * raw[config.PORT_RIGHT_WHEEL][0],
            "arm": config.ARM_MOTOR_SIGN_DOWN * raw[config.PORT_ARM][1],
            "grip": config.GRIPPER_MOTOR_SIGN_OPEN * raw[config.PORT_GRIPPER][1],
        }
        with self._lock:
            self._state = state
            if self._zero is None:
                self._zero = {"arm": state["arm"], "grip": state["grip"]}
                self._target = dict(self._zero)

    def drive(self, left: int, right: int) -> None:
        """Wheel speeds just sent, robot terms."""
        with self._lock:
            self._cmd = {"left": left, "right": right}

    def step(self, motor: str, degrees: float) -> None:
        """A press just sent "arm" or "grip" this many degrees, robot terms (+ = down / open)."""
        with self._lock:
            if self._state is None:
                return
            now, target = self._state[motor], self._target[motor]
            # Moves are relative to where the motor is when they run. If the last move
            # did not get there (the gripper closed on an object), start from where it is.
            base = target if abs(target - now) < abs(degrees) else now
            self._target[motor] = base + degrees

    def pad(self, pad: dict) -> None:
        with self._lock:
            self._pad = pad

    def not_ready(self) -> list[str]:
        """What is still missing before an episode can start."""
        missing = [] if self._zero is not None else ["motor readings from the Pi"]
        for name, cam in self.cameras.items():
            frame, age = cam.get()
            if frame is None or age > STALE_S:
                missing.append(f"{name} camera ({cam.status})")
        return missing

    # ── episodes ─────────────────────────────────────────────────────────────

    @property
    def recording(self) -> bool:
        return self._episode is not None

    @property
    def frames(self) -> int:
        return self._episode["n"] if self._episode else 0

    def start(self) -> Path:
        if self.recording:
            raise RuntimeError("already recording")
        missing = self.not_ready()
        if missing:
            raise RuntimeError("not ready, waiting for: " + ", ".join(missing))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        taken = [int(p.name[3:]) for p in self.out_dir.glob("ep_*") if p.name[3:].isdigit()]
        folder = self.out_dir / f"ep_{max(taken, default=-1) + 1:04d}"
        folder.mkdir()
        writers = {}
        for name in self.cameras:
            w = cv2.VideoWriter(str(folder / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"avc1"), FPS, VIDEO_SIZE)
            if not w.isOpened():  # this OpenCV build has no H.264
                w = cv2.VideoWriter(str(folder / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, VIDEO_SIZE)
            writers[name] = w
        self._episode = {
            "folder": folder, "n": 0, "rows": (folder / "frames.jsonl").open("w"), "writers": writers,
            "started": time.time(), "stale": {name: 0 for name in self.cameras}, "late_ticks": 0,
            "stop": threading.Event(),
        }
        self._thread = threading.Thread(target=self._run, args=(self._episode,), daemon=True)
        self._thread.start()
        return folder

    def stop(self) -> Path:
        """Stop sampling. Then finish() to keep the episode or discard() to delete it."""
        ep = self._episode
        if not ep["stop"].is_set():
            ep["stop"].set()
            self._thread.join()
            ep["rows"].close()
            for w in ep["writers"].values():
                w.release()
        return ep["folder"]

    def finish(self, success: bool, notes: str = "") -> Path:
        ep, self._episode = self._episode, None
        meta = {
            "task": self.task, "success": success, "frames": ep["n"], "driver": self.driver,
            "date": time.strftime("%Y-%m-%d", time.localtime(ep["started"])), "notes": notes,
            "fps": FPS, "seconds": round(ep["n"] / FPS, 1),
            "units": {
                "state.left_speed/right_speed": "measured wheel speed -100..100, + forward",
                "state.arm_pos/grip_pos": "deg since recorder start, + down / + open",
                "action.left/right": "commanded wheel speed -100..100, + forward",
                "action.arm/grip": "target angle of the last button press, same zero as state",
            },
            "zero_encoder_deg": self._zero,
            "stale_camera_frames": ep["stale"], "late_ticks": ep["late_ticks"],
        }
        (ep["folder"] / "episode.json").write_text(json.dumps(meta, indent=2) + "\n")
        return ep["folder"]

    def discard(self) -> Path:
        self.stop()
        ep, self._episode = self._episode, None
        shutil.rmtree(ep["folder"], ignore_errors=True)
        return ep["folder"]

    # ── sampling ─────────────────────────────────────────────────────────────

    def _run(self, ep: dict) -> None:
        period = 1 / FPS
        next_t = time.monotonic()
        while not ep["stop"].is_set():
            self._tick(ep)
            next_t += period
            delay = next_t - time.monotonic()
            if delay < 0:  # fell behind: skip ahead rather than bunching frames together
                ep["late_ticks"] += 1
                next_t = time.monotonic()
            elif ep["stop"].wait(delay):
                break

    def _tick(self, ep: dict) -> None:
        t = time.time()
        with self._lock:
            s, z, cmd, target, pad = self._state, self._zero, self._cmd, dict(self._target), self._pad
        frames = {}
        for name, cam in self.cameras.items():
            frame, age = cam.get()
            if age > STALE_S:
                ep["stale"][name] += 1
            frames[name] = frame
        row = {
            "i": ep["n"],
            "t": round(t, 4),
            "state": {"left_speed": s["left_speed"], "right_speed": s["right_speed"],
                      "arm_pos": round(s["arm"] - z["arm"], 1), "grip_pos": round(s["grip"] - z["grip"], 1)},
            "action": {"left": cmd["left"], "right": cmd["right"],
                       "arm": round(target["arm"] - z["arm"], 1), "grip": round(target["grip"] - z["grip"], 1)},
            "gamepad": pad,
        }
        ep["rows"].write(json.dumps(row) + "\n")
        for name, frame in frames.items():
            ep["writers"][name].write(frame)
        ep["n"] += 1
