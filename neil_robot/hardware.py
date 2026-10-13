"""
Robot hardware access: Pi system checks, Build HAT, motors, camera.

Only move_motor() moves anything. Everything else is read-only.
"""
from __future__ import annotations

import base64
import time

from neil_robot import config
from neil_robot.rpi_client import RPiClient, get_client

# ── Pi-side scripts (run by RPiClient.run_python; PARAMS and emit() are provided) ──

_SYSTEM_INFO = r"""
import os, platform, sys, grp, pwd, importlib

def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None

info = {"hostname": platform.node(), "python": sys.version.split()[0]}
osr = read("/etc/os-release") or ""
info["os"] = next((l.split("=", 1)[1].strip('"') for l in osr.splitlines() if l.startswith("PRETTY_NAME=")), None)
info["model"] = (read("/proc/device-tree/model") or "").strip("\x00") or None

# Build HAT talks over the UART: it needs enable_uart=1 and no serial login console.
boot_cfg = read("/boot/firmware/config.txt") or read("/boot/config.txt") or ""
active = [l.strip() for l in boot_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
info["enable_uart"] = "enable_uart=1" in active
cmdline = read("/boot/firmware/cmdline.txt") or read("/boot/cmdline.txt") or ""
info["serial_console_on_uart"] = "console=serial0" in cmdline or "console=ttyAMA0" in cmdline or "console=ttyS0" in cmdline
info["serial0"] = os.path.realpath("/dev/serial0") if os.path.exists("/dev/serial0") else None

user = pwd.getpwuid(os.getuid()).pw_name
info["user"] = user
info["groups"] = sorted(g.gr_name for g in grp.getgrall() if user in g.gr_mem)

pkgs = {}
for name in ("buildhat", "picamera2", "numpy", "PIL"):
    try:
        mod = importlib.import_module(name)
        pkgs[name] = getattr(mod, "__version__", "installed")
    except Exception as e:
        pkgs[name] = None
info["packages"] = pkgs
emit(info)
"""

# Connecting to the HAT may upload its firmware the first time (takes ~10 s).
# Reads only: input voltage, what's plugged into each port, and motor positions.
_HAT_STATUS = r"""
from buildhat import Hat, Motor
hat = Hat()
status = {"vin": hat.get_vin(), "ports": {}}
for port, dev in hat.get().items():
    entry = {"name": dev.get("name"), "type_id": dev.get("typeid"),
             "description": dev.get("description"), "connected": dev.get("connected")}
    if dev.get("connected") and "Motor" in (dev.get("name") or "") + (dev.get("description") or ""):
        try:
            m = Motor(port)
            entry["position"] = m.get_position()
            entry["absolute_position"] = m.get_aposition()
        except Exception as e:
            entry["error"] = repr(e)
    status["ports"][port] = entry
emit(status)
"""

_CAPTURE_STILL = r"""
import base64, io, time
from libcamera import Transform
from picamera2 import Picamera2
cams = Picamera2.global_camera_info()
if not cams:
    raise RuntimeError("no camera detected")
cam = Picamera2()
try:
    flip = PARAMS["rotation"] == 180
    cam.configure(cam.create_still_configuration(
        main={"size": (PARAMS["width"], PARAMS["height"])},
        transform=Transform(hflip=flip, vflip=flip),
    ))
    cam.start()
    time.sleep(PARAMS["warmup"])
    buf = io.BytesIO()
    cam.capture_file(buf, format="jpeg")
finally:
    cam.stop()
    cam.close()
emit({"camera": cams[0].get("Model"), "jpeg_b64": base64.b64encode(buf.getvalue()).decode()})
"""

# Records with the Pi's hardware MJPEG encoder: the file is the frames' JPEGs back to back.
_RECORD_MJPEG = r"""
import os, time
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
from libcamera import Transform
cams = Picamera2.global_camera_info()
if not cams:
    raise RuntimeError("no camera detected")
cam = Picamera2()
try:
    cam.configure(cam.create_video_configuration(
        main={"size": (PARAMS["width"], PARAMS["height"])},
        controls={"FrameRate": PARAMS["fps"]},
        transform=Transform(hflip=PARAMS["rotation"] == 180, vflip=PARAMS["rotation"] == 180),
    ))
    cam.start_recording(MJPEGEncoder(), FileOutput(PARAMS["path"]))
    t0 = time.monotonic()
    time.sleep(PARAMS["seconds"])
    cam.stop_recording()
    elapsed = time.monotonic() - t0
finally:
    cam.close()
emit({"camera": cams[0].get("Model"), "path": PARAMS["path"],
      "bytes": os.path.getsize(PARAMS["path"]), "elapsed_s": elapsed})
"""

# Move by +degrees and back by -degrees, reporting positions after each leg.
_MOVE_MOTOR = r"""
import time
from buildhat import Motor
m = Motor(PARAMS["port"])
try:
    p0 = m.get_position()
    m.run_for_degrees(PARAMS["degrees"], speed=PARAMS["speed"])
    time.sleep(0.3)
    p1 = m.get_position()
    p2 = None
    if PARAMS["return_to_start"]:
        m.run_for_degrees(-PARAMS["degrees"], speed=PARAMS["speed"])
        time.sleep(0.3)
        p2 = m.get_position()
finally:
    m.stop()
emit({"port": PARAMS["port"], "start": p0, "after_move": p1, "after_return": p2,
      "moved": p1 - p0, "returned": None if p2 is None else p2 - p1})
"""


# ── host-side API ─────────────────────────────────────────────────────────────

def system_info(client: RPiClient | None = None) -> dict:
    return (client or get_client()).run_python(_SYSTEM_INFO, timeout=30)


def hat_status(client: RPiClient | None = None) -> dict:
    return (client or get_client()).run_python(_HAT_STATUS, timeout=90)


def capture_still(
    width: int = config.CAMERA_WIDTH,
    height: int = config.CAMERA_HEIGHT,
    client: RPiClient | None = None,
) -> tuple[str, bytes]:
    """Return (camera model, JPEG bytes)."""
    params = {"width": width, "height": height, "warmup": config.CAMERA_WARMUP_S,
              "rotation": config.CAMERA_ROTATION}
    r = (client or get_client()).run_python(_CAPTURE_STILL, params, timeout=60)
    return r["camera"], base64.b64decode(r["jpeg_b64"])


def record_video(
    local_path,
    seconds: float = 5.0,
    width: int = config.VIDEO_WIDTH,
    height: int = config.VIDEO_HEIGHT,
    fps: int = config.VIDEO_FPS,
    rotation: int = config.CAMERA_ROTATION,
    client: RPiClient | None = None,
) -> dict:
    """Record *seconds* of video on the Pi camera and copy the MJPEG file to *local_path*."""
    client = client or get_client()
    remote = f"/tmp/neil_clip_{int(time.time() * 1000)}.mjpeg"
    if rotation not in (0, 180):
        raise ValueError("rotation must be 0 or 180")
    params = {"path": remote, "seconds": seconds, "width": width, "height": height, "fps": fps,
              "rotation": rotation}
    info = client.run_python(_RECORD_MJPEG, params, timeout=seconds + 60)
    client.fetch_file(remote, local_path, delete_remote=True)
    return info


def move_motor(
    port: str,
    degrees: int = config.MOTOR_TEST_DEGREES,
    speed: int = config.MOTOR_TEST_SPEED,
    return_to_start: bool = True,
    client: RPiClient | None = None,
) -> dict:
    """Turn the motor on *port* by *degrees* (and back, by default). This MOVES the robot."""
    port = port.upper()
    if port not in config.PORTS:
        raise ValueError(f"port must be one of {config.PORTS}")
    if not 0 < abs(degrees) <= config.MOTOR_MAX_DEGREES:
        raise ValueError(f"degrees must be within ±{config.MOTOR_MAX_DEGREES}")
    if not config.MOTOR_MIN_SPEED <= speed <= config.MOTOR_MAX_SPEED:
        raise ValueError(f"speed must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")
    params = {"port": port, "degrees": degrees, "speed": speed, "return_to_start": return_to_start}
    return (client or get_client()).run_python(_MOVE_MOTOR, params, timeout=60)
