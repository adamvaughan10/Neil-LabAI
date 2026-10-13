"""
Live Rerun dashboard: both cameras and the motors.

    Pi camera   the robot's own camera: the Pi's MJPEG server on PI_CAMERA_URL if one
                is running, else streamed by pi/camera_stream.py
    iPhone      the external camera (SimpleIPCamera app, IPHONE_CAMERA_URL)
    Arm         angle, ° since the dashboard started, + = down
    Gripper     angle, ° since the dashboard started, + = open
    Wheels      speed (-100..100, + = forward), measured and commanded
    Now         the latest numbers and whether each camera is live

The motor readouts come from pi/gamepad_server.py's "state" lines (pass each to
log_state), the same Pi process that drives the motors, so nothing else touches
the Build HAT.

Viewer modes, as in lego-robot-mcp's viz.py:
    spawn    open the Rerun desktop viewer (default)
    serve    serve a web viewer, open http://localhost:9090
    connect  send to a viewer that is already running (RERUN_ADDR)

Needs rerun-sdk on the laptop: pip install rerun-sdk==0.31.3
"""
from __future__ import annotations

import base64
import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path

from neil_robot import config
from neil_robot.rpi_client import RPiClient

_ROOT = Path(__file__).resolve().parent.parent

# How often pi/gamepad_server.py reports the motors when the dashboard is on.
STATE_HZ = float(os.getenv("STATE_HZ", "10"))
# Pi camera feed: small and slow enough to stream over SSH.
STREAM_WIDTH = int(os.getenv("STREAM_WIDTH", "640"))
STREAM_HEIGHT = int(os.getenv("STREAM_HEIGHT", "480"))
STREAM_FPS = int(os.getenv("STREAM_FPS", "10"))
# If an MJPEG camera server is already running on the Pi (it holds the camera, and only
# one program can), read it here instead. Empty: always stream with pi/camera_stream.py.
PI_CAMERA_URL = os.getenv("PI_CAMERA_URL", f"http://{config.RPI_HOST}:8765/")
# The camera server running on the Pi on 2026-10-13 (/tmp/neil_cam_server.py) sends red
# and blue swapped (people look blue). 1 swaps them back; set 0 if colors look wrong.
PI_CAMERA_SWAP_RB = os.getenv("PI_CAMERA_SWAP_RB", "1") == "1"
# External iPhone camera: the SimpleIPCamera app's MJPEG URL, shown on its screen.
# lego-robot-mcp's default; empty turns the iPhone feed off.
IPHONE_CAMERA_URL = os.getenv("IPHONE_CAMERA_URL", "http://192.168.8.81:8080/stream.mjpeg")
IPHONE_CAMERA_ROTATION = int(os.getenv("IPHONE_CAMERA_ROTATION", "90"))  # clockwise: 0, 90, 180, 270


def start_pi_script(client: RPiClient, path: Path, settings: dict):
    """Send *path* to the Pi, run it with *settings* as argv[1], wait for its "ready" line.

    Returns (stdin, stdout). Closing stdin is how the script is told to stop.
    """
    code = path.read_text()
    stdin, stdout, _ = client.connect().exec_command(
        f"python3 -u -c {shlex.quote(code)} {shlex.quote(json.dumps(settings))} 2>&1")
    output = []
    for line in stdout:  # wait for the HAT or camera (the HAT may load firmware first)
        if line.strip() == "ready":
            return stdin, stdout
        output.append(line)
    raise RuntimeError(f"{path.name} stopped before it was ready:\n" + "".join(output[-20:]))


MODES = ("spawn", "serve", "connect")
RERUN_ADDR = os.getenv("RERUN_ADDR", "rerun+http://127.0.0.1:9876")
WINDOW_S = 20  # seconds of history the plots show
IPHONE_RETRY_S = 3

_BLUE, _RED = [66, 133, 244], [234, 67, 53]
_ROTATE = {90: 0, 180: 1, 270: 2}  # cv2.ROTATE_90_CLOCKWISE, ROTATE_180, ROTATE_90_COUNTERCLOCKWISE


class Dashboard:
    def __init__(self, mode: str = "spawn", pi_camera: bool = True, iphone_url: str = IPHONE_CAMERA_URL):
        import rerun as rr
        import rerun.blueprint as rrb
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self._rr = rr
        rr.init("neil_robot", recording_id=f"neil_{int(time.time())}")
        if mode == "spawn":
            venv_rerun = os.path.join(os.path.dirname(sys.executable), "rerun")
            rr.spawn(executable_path=venv_rerun if os.path.isfile(venv_rerun) else None, memory_limit="25%")
        elif mode == "serve":
            rr.serve_web_viewer(connect_to=rr.serve_grpc())
        else:
            rr.connect_grpc(RERUN_ADDR)

        recent = [rrb.VisibleTimeRange("time", start=rrb.TimeRangeBoundary.cursor_relative(seconds=-WINDOW_S),
                                       end=rrb.TimeRangeBoundary.cursor_relative())]
        rr.send_blueprint(rrb.Blueprint(
            rrb.Vertical(
                rrb.Horizontal(
                    rrb.Spatial2DView(name="Pi camera", origin="camera/pi"),
                    rrb.Spatial2DView(name="iPhone", origin="camera/iphone"),
                ),
                rrb.Horizontal(
                    rrb.TimeSeriesView(name="Arm angle (°, + down)", origin="arm", time_ranges=recent),
                    rrb.TimeSeriesView(name="Gripper angle (°, + open)", origin="gripper", time_ranges=recent),
                    rrb.TimeSeriesView(name="Wheel speed (+ forward)", origin="wheels", time_ranges=recent),
                    rrb.TextDocumentView(name="Now", origin="now"),
                ),
                row_shares=[3, 2],
            ),
            collapse_panels=True,
        ))
        for name in ("arm", "gripper"):
            rr.log(f"{name}/angle", rr.SeriesLines(names="angle", colors=[_BLUE], widths=2), static=True)
        for side, color in (("left", _BLUE), ("right", _RED)):
            rr.log(f"wheels/{side}/measured", rr.SeriesLines(names=f"{side}", colors=[color], widths=2), static=True)
            rr.log(f"wheels/{side}/commanded", rr.SeriesLines(names=f"{side} commanded", colors=[color], widths=1),
                   static=True)

        self._zero: dict[str, float] = {}
        self._drive = (0, 0)  # commanded wheel speeds, robot terms
        self._latest: dict = {}
        self._cameras = {"Pi camera": "off", "iPhone": "off"}
        self._stop = threading.Event()
        self._pi_stdin = None
        self._pi_client: RPiClient | None = None
        self._threads = []
        if pi_camera:
            self._start(self._run_pi_camera)
        if iphone_url:
            self._start(self._run_iphone, iphone_url)

    def _start(self, target, *args) -> None:
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    # ── cameras ──────────────────────────────────────────────────────────────

    def _run_pi_camera(self) -> None:
        # Share the Pi's MJPEG camera server if one is running (only one program can
        # open the camera), else stream it with pi/camera_stream.py.
        if PI_CAMERA_URL and self._read_mjpeg("Pi camera", "camera/pi", PI_CAMERA_URL, 0, PI_CAMERA_SWAP_RB):
            return
        if self._stop.is_set():
            return
        rr = self._rr
        self._cameras["Pi camera"] = "starting"
        settings = {"width": STREAM_WIDTH, "height": STREAM_HEIGHT, "fps": STREAM_FPS,
                    "rotation": config.CAMERA_ROTATION}
        try:
            # Its own SSH connection, so video never delays the motor commands.
            self._pi_client = RPiClient()
            self._pi_stdin, stdout = start_pi_script(self._pi_client, _ROOT / "pi" / "camera_stream.py", settings)
        except Exception as exc:
            reason = "camera in use by another program" if "in use by another process" in str(exc) else \
                str(exc).strip().splitlines()[-1][:120]
            self._cameras["Pi camera"] = f"unavailable: {reason}"
            print(f"\nPi camera unavailable: {reason}", file=sys.stderr)
            return
        self._cameras["Pi camera"] = "live (streamed over SSH)"
        try:
            for line in stdout:
                if line.startswith("jpeg "):
                    rr.set_time("time", timestamp=time.time())
                    rr.log("camera/pi", rr.EncodedImage(contents=base64.b64decode(line[5:]), media_type="image/jpeg"))
        except (OSError, EOFError):
            pass
        self._cameras["Pi camera"] = "stream ended"

    def _run_iphone(self, url: str) -> None:
        while not self._stop.is_set():
            if not self._read_mjpeg("iPhone", "camera/iphone", url, IPHONE_CAMERA_ROTATION):
                self._cameras["iPhone"] = f"no stream at {url}, retrying"
            self._stop.wait(IPHONE_RETRY_S)

    def _read_mjpeg(self, name: str, entity: str, url: str, rotation: int, swap_rb: bool = False) -> bool:
        """Log an MJPEG stream until it ends or close(); False if it never opened."""
        import cv2
        rr = self._rr
        self._cameras[name] = f"connecting to {url}"
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            return False
        period, last = 1 / STREAM_FPS, 0.0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()  # read every frame so the stream doesn't fall behind
                if not ok:
                    break
                if time.monotonic() - last < period:
                    continue
                last = time.monotonic()
                if rotation in _ROTATE:
                    frame = cv2.rotate(frame, _ROTATE[rotation])
                self._cameras[name] = f"live ({url})"
                rr.set_time("time", timestamp=time.time())
                rr.log(entity, rr.Image(frame, color_model="RGB" if swap_rb else "BGR").compress(jpeg_quality=75))
        finally:
            cap.release()
        self._cameras[name] = f"stream ended ({url})"
        return True

    # ── motors ───────────────────────────────────────────────────────────────

    def log_drive(self, left: int, right: int) -> None:
        """The wheel speeds the laptop asked for, robot terms (+ = forward)."""
        self._drive = (left, right)
        rr = self._rr
        rr.set_time("time", timestamp=time.time())
        rr.log("wheels/left/commanded", rr.Scalars(left))
        rr.log("wheels/right/commanded", rr.Scalars(right))

    def log_state(self, state: dict) -> None:
        """One report from pi/gamepad_server.py: {port: [speed, angle]}, raw motor values."""
        if "error" in state:
            return
        signs = {"left": (config.PORT_LEFT_WHEEL, config.LEFT_WHEEL_SIGN_FORWARD),
                 "right": (config.PORT_RIGHT_WHEEL, config.RIGHT_WHEEL_SIGN_FORWARD),
                 "arm": (config.PORT_ARM, config.ARM_MOTOR_SIGN_DOWN),
                 "gripper": (config.PORT_GRIPPER, config.GRIPPER_MOTOR_SIGN_OPEN)}
        robot = {name: [sign * v for v in state[port]] for name, (port, sign) in signs.items() if port in state}
        rr = self._rr
        rr.set_time("time", timestamp=time.time())
        for name in ("arm", "gripper"):
            if name in robot:
                angle = robot[name][1]
                self._latest[name] = angle - self._zero.setdefault(name, angle)
                rr.log(f"{name}/angle", rr.Scalars(self._latest[name]))
        for side in ("left", "right"):
            if side in robot:
                self._latest[side] = robot[side][0]
                rr.log(f"wheels/{side}/measured", rr.Scalars(self._latest[side]))
        rr.log("now", rr.TextDocument(self._table(), media_type=rr.MediaType.MARKDOWN))

    def _table(self) -> str:
        def num(v, unit=""):
            return "–" if v is None else f"{v:+.0f}{unit}"
        got = self._latest.get
        rows = [
            ("Arm", num(got("arm"), "°"), ""),
            ("Gripper", num(got("gripper"), "°"), ""),
            ("Left wheel", num(got("left")), num(self._drive[0])),
            ("Right wheel", num(got("right")), num(self._drive[1])),
        ]
        lines = ["| Motor | Measured | Commanded |", "|---|---|---|"]
        lines += [f"| {' | '.join(r)} |" for r in rows]
        lines += ["", "Angles are ° since the dashboard started.", ""]
        lines += [f"**{name}:** {status}  " for name, status in self._cameras.items()]
        return "\n".join(lines)

    def close(self) -> None:
        self._stop.set()
        if self._pi_stdin:
            try:
                self._pi_stdin.channel.shutdown_write()  # pi/camera_stream.py frees the camera and exits
            except OSError:
                pass
        if self._pi_client:
            self._pi_client.close()
        for t in self._threads:
            t.join(timeout=3)
        self._rr.disconnect()
