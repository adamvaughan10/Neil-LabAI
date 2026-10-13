"""
Live MJPEG streams from both cameras.

    with PiCameraStream() as pi, ExternalCameraStream() as ext:
        frame = pi.latest()        # Frame(jpeg=bytes, ts=clock.now(), index=n) or None

To save frames, use neil_robot.recorder.SyncRecorder: it samples the streams at a
fixed rate. The streams themselves never store anything but the newest frame.

Each stream reads in a background thread and keeps the newest frame. Frames
are kept as the JPEG bytes the camera sent (no re-encoding), stamped with the
laptop's high-resolution clock on arrival (neil_robot.clock), minus the camera's
known delay (latency_s), so the two cameras can be lined up in time.

The Pi camera has no stream of its own: PiCameraStream uploads a small MJPEG
HTTP server to the Pi, starts it over SSH, and reads it like the phone's.
"""
from __future__ import annotations

import http.client
import logging
import threading
import time
import urllib.parse
from dataclasses import dataclass

import cv2
import numpy as np

from neil_robot import clock, config
from neil_robot.rpi_client import RPiClient
from neil_robot.video import rotate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    ts: float     # clock.now() when the frame arrived, minus the stream's latency_s
    index: int    # count of frames received on this stream

    def decode(self, rotation: int = 0) -> np.ndarray:
        img = cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR)
        return rotate(img, rotation)


class MjpegStream:
    """Reads a multipart/x-mixed-replace MJPEG stream over HTTP in a background thread."""

    name = "stream"
    rotation = 0  # applied by Frame.decode() callers, never to the stored JPEGs
    latency_s = 0.0  # capture-to-arrival delay, subtracted from every timestamp

    def __init__(self, url: str):
        self.url = url
        self._latest: Frame | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: http.client.HTTPConnection | None = None
        self.error: Exception | None = None
        self.count = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, wait_s: float = config.STREAM_CONNECT_TIMEOUT) -> "MjpegStream":
        """Start reading; returns once the first frame arrives (raises if none within *wait_s*)."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + wait_s
        while self._latest is None and time.monotonic() < deadline:
            if self.error:
                raise RuntimeError(f"{self.name}: {self.error}") from self.error
            time.sleep(0.05)
        if self._latest is None:
            self.stop()
            raise RuntimeError(f"{self.name}: no frame from {self.url} within {wait_s:g} s")
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._conn:
            try:
                self._conn.close()  # unblocks a read in progress
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── frames ────────────────────────────────────────────────────────────────

    def latest(self) -> Frame | None:
        return self._latest

    # ── reader ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            u = urllib.parse.urlsplit(self.url)
            if u.scheme != "http":
                raise ValueError(f"only http:// streams are supported, got {self.url}")
            self._conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=config.STREAM_CONNECT_TIMEOUT)
            self._conn.request("GET", u.path + (f"?{u.query}" if u.query else ""))
            resp = self._conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} {resp.reason}")
            ctype = resp.getheader("Content-Type", "")
            if "multipart" not in ctype:
                raise RuntimeError(f"not an MJPEG stream (Content-Type: {ctype})")
            while not self._stop.is_set():
                jpeg = self._read_part(resp)
                if jpeg is None:
                    raise RuntimeError("stream ended")
                self._push(jpeg)
        except Exception as exc:  # noqa: BLE001
            if not self._stop.is_set():
                self.error = exc
                log.warning("%s stopped: %s", self.name, exc)

    @staticmethod
    def _read_part(resp) -> bytes | None:
        """Read one part: skip to its headers, then read the JPEG by Content-Length,
        or up to the JPEG end marker when the server doesn't send a length."""
        length = None
        while True:
            line = resp.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                if length is not None:
                    break
                continue
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
            elif line.startswith(b"\xff\xd8"):  # no headers: JPEG starts straight away
                data = line
                while not data.rstrip().endswith(b"\xff\xd9"):
                    more = resp.readline()
                    if not more:
                        return None
                    data += more
                return data.rstrip(b"\r\n")
        data = resp.read(length)
        return data if len(data) == length else None

    def _push(self, jpeg: bytes) -> None:
        self.count += 1
        frame = Frame(jpeg, clock.now() - self.latency_s, self.count)
        self._latest = frame


class ExternalCameraStream(MjpegStream):
    name = "external"

    def __init__(self, url: str = config.EXTERNAL_CAMERA_URL, rotation: int = config.EXTERNAL_CAMERA_ROTATION):
        super().__init__(url)
        self.rotation = rotation
        self.latency_s = config.EXTERNAL_CAMERA_LATENCY_S


# Runs on the Pi. Hardware MJPEG encoder -> latest-frame buffer -> HTTP clients.
_PI_STREAM_SERVER = r"""
import io, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

W, H, FPS, PORT, FLIP = (int(a) for a in sys.argv[1:6])

class Latest(io.BufferedIOBase):
    def __init__(self):
        self.frame, self.cond = b"", threading.Condition()
    def write(self, buf):
        with self.cond:
            self.frame = bytes(buf)
            self.cond.notify_all()
        return len(buf)

latest = Latest()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with latest.cond:
                    latest.cond.wait()
                    frame = latest.frame
                self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
    def log_message(self, *a):
        pass

cam = Picamera2()
cam.configure(cam.create_video_configuration(
    main={"size": (W, H)}, controls={"FrameRate": FPS},
    transform=Transform(hflip=bool(FLIP), vflip=bool(FLIP))))
cam.start_recording(MJPEGEncoder(), FileOutput(latest))
print("READY", flush=True)
try:
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
finally:
    cam.stop_recording()
    cam.close()
"""

_PI_SERVER_PATH = "/tmp/neil_cam_server.py"


class PiCameraStream(MjpegStream):
    """Starts the stream server on the Pi, reads it, and shuts it down on stop()."""

    name = "pi"

    def __init__(
        self,
        width: int = config.PI_STREAM_WIDTH,
        height: int = config.PI_STREAM_HEIGHT,
        fps: int = config.PI_STREAM_FPS,
        port: int = config.PI_STREAM_PORT,
    ):
        super().__init__(f"http://{config.RPI_HOST}:{port}/")
        self.args = (width, height, fps, port, 1 if config.CAMERA_ROTATION == 180 else 0)
        self.latency_s = config.PI_CAMERA_LATENCY_S
        self._client = RPiClient()
        self._channel = None

    def start(self, wait_s: float = config.STREAM_CONNECT_TIMEOUT) -> "PiCameraStream":
        ssh = self._client.connect()
        # Clear a server left behind by a run that didn't shut down cleanly; it would hold the camera.
        self._client.run_shell(f"pkill -f {_PI_SERVER_PATH}; sleep 0.3", timeout=10)
        with ssh.open_sftp() as sftp, sftp.open(_PI_SERVER_PATH, "w") as f:
            f.write(_PI_STREAM_SERVER)
        # A pty ties the server's life to this channel: closing it hangs the server up.
        self._channel = ssh.get_transport().open_session()
        self._channel.get_pty()
        self._channel.exec_command(f"python3 {_PI_SERVER_PATH} {' '.join(map(str, self.args))}")
        deadline = time.monotonic() + 15
        out = b""
        while b"READY" not in out:
            if self._channel.recv_ready():
                out += self._channel.recv(4096)
            elif self._channel.exit_status_ready() or time.monotonic() > deadline:
                out += self._channel.recv(65536) if self._channel.recv_ready() else b""
                self._shutdown_server()
                raise RuntimeError(f"Pi stream server didn't start:\n{out.decode(errors='replace')[-1500:]}")
            else:
                time.sleep(0.05)
        try:
            return super().start(wait_s)
        except Exception:
            self._shutdown_server()
            raise

    def stop(self) -> None:
        super().stop()
        self._shutdown_server()

    def _shutdown_server(self) -> None:
        if self._channel:
            self._channel.close()
            self._channel = None
        try:
            self._client.run_shell(f"pkill -f {_PI_SERVER_PATH}", timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._client.close()
