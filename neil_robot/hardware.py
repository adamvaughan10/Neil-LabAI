"""
Robot hardware access: Pi system checks, Build HAT, motors, camera.

move_motor(), arm_down_up(), drive_and_arm_sequence() and LiveMotors move things.
Everything else is read-only.
"""
from __future__ import annotations

import base64
import json
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

# Lower the arm, pause, then raise it back by however far it actually went down
# (not the requested amount, so it never drives into the top stop).
# Positions are sampled throughout so the motion can be lined up with video.
_ARM_DOWN_UP = r"""
import time
from buildhat import Motor
arm = Motor(PARAMS["port"])
sign = PARAMS["sign_down"]
samples, t0 = [], time.monotonic()
def sample(phase):
    samples.append({"t": round(time.monotonic() - t0, 3), "phase": phase, "pos": arm.get_position()})
try:
    time.sleep(PARAMS["delay_s"])
    sample("start")
    arm.run_for_degrees(sign * PARAMS["degrees"], speed=PARAMS["speed"])
    time.sleep(0.5)
    sample("lowered")
    went_down = (samples[-1]["pos"] - samples[0]["pos"]) * sign
    if went_down > 0:
        arm.run_for_degrees(-sign * went_down, speed=PARAMS["speed"])
    time.sleep(0.5)
    sample("raised")
finally:
    arm.stop()
p0, p1, p2 = (s["pos"] for s in samples)
emit({"samples": samples, "lowered_deg": (p1 - p0) * sign, "raised_deg": (p1 - p2) * sign,
      "net_deg_from_start": (p2 - p0) * sign})
"""

# Drive forward, drive back, then raise the arm and lower it again.
# The arm holds its position between moves (release=False) instead of going
# limp, so gravity can't pull it past its target.
_SEQUENCE = r"""
import time
from buildhat import Motor, MotorPair
P = PARAMS
pair = MotorPair(P["left"], P["right"])
left, right = pair._leftmotor, pair._rightmotor  # don't create second Motor objects for these ports
arm = Motor(P["arm"])
arm.release = False
steps, t0 = [], time.monotonic()
def record(step):
    steps.append({"t": round(time.monotonic() - t0, 3), "step": step,
                  "left": left.get_position(), "right": right.get_position(), "arm": arm.get_position()})
try:
    record("start")
    for name, direction in (("forward", 1), ("backward", -1)):
        pair.run_for_seconds(P["drive_s"], direction * P["lsign"] * P["drive_speed"],
                             direction * P["rsign"] * P["drive_speed"])
        time.sleep(P["pause_s"])
        record(name)
    arm.run_for_degrees(-P["arm_sign_down"] * P["arm_deg"], speed=P["arm_speed"])
    time.sleep(P["pause_s"])
    record("arm_up")
    arm.run_for_degrees(P["arm_sign_down"] * P["arm_deg"], speed=P["arm_speed"])
    time.sleep(P["pause_s"])
    record("arm_down")
finally:
    pair.stop()
emit({"steps": steps})
"""


# Live control: runs each motor at the speed the laptop last sent, one JSON line
# per command, e.g. {"A": 30, "B": -30, "C": 0, "D": 0, "pwm": {"C": -0.3}}.
# A port at speed 0 idles as PARAMS["idle"] says: "coast" (limp) or "hold"
# (position control at where it stopped, so the arm doesn't drop). Holding at
# speed 0 in speed mode made the motors shake, so it isn't used. A "pwm" entry
# instead drives an idle port with that fixed power (-1..1), no feedback loop:
# used to keep the gripper squeezing an object.
# If no line arrives for PARAMS["watchdog_s"], every port idles.
# When stdin closes the motors coast and the script exits.
_LIVE_MOTORS = r"""
import os, select, sys, time
from buildhat import Motor
motors = {p: Motor(p) for p in PARAMS["ports"]}
current = {p: None for p in motors}
def hold(m):
    # buildhat's own position-hold command (from Motor._run_positional_ramp), aimed at
    # the current position. Written directly: its ramp form expects a Future per move.
    rot = m.get_position() / 360
    m._write(f"port {m.port}; select 0 ; selrate {m._interval}; "
             f"pid {m.port} 0 1 s4 0.0027777778 0 5 0 .1 3 0.01; set {rot}\r")
def apply(cmd):
    for p, m in motors.items():
        speed = max(-100, min(100, int(cmd.get(p, 0))))
        pwm = cmd.get("pwm", {}).get(p)
        want = ("speed", speed) if speed else ("pwm", pwm) if pwm else ("idle",)
        if want == current[p]:
            continue
        m.stop()  # coast, and reset buildhat's run mode so start() reconfigures
        if want[0] == "speed":
            m.start(speed)
        elif want[0] == "pwm":
            m.pwm(max(-1.0, min(1.0, pwm)))
        elif PARAMS["idle"][p] == "hold":
            hold(m)
        current[p] = want
apply({})
emit({"ready": True})
fd, buf, last = sys.stdin.fileno(), b"", time.monotonic()
try:
    while True:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            if lines:
                apply(_json.loads(lines[-1]))  # only the newest command matters
                last = time.monotonic()
        elif time.monotonic() - last > PARAMS["watchdog_s"]:
            apply({})
finally:
    for m in motors.values():
        m.stop()
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


def arm_down_up(
    degrees: int = config.ARM_TEST_DEGREES,
    speed: int = config.ARM_TEST_SPEED,
    delay_s: float = 0.0,
    client: RPiClient | None = None,
) -> dict:
    """Lower the arm by *degrees* and raise it back. This MOVES the arm.

    Degrees in the result are positive = down.
    """
    if not 0 < degrees <= 90:
        raise ValueError("degrees must be 1..90")
    if not config.ARM_SPEED_MIN <= speed <= config.ARM_SPEED_MAX:
        raise ValueError(f"arm speed must be {config.ARM_SPEED_MIN}..{config.ARM_SPEED_MAX}")
    params = {"port": config.PORT_ARM, "degrees": degrees, "speed": speed, "delay_s": delay_s,
              "sign_down": config.ARM_MOTOR_SIGN_DOWN}
    return (client or get_client()).run_python(_ARM_DOWN_UP, params, timeout=60 + delay_s)


def drive_and_arm_sequence(
    drive_s: float = config.DRIVE_TEST_SECONDS,
    drive_speed: int = config.DRIVE_TEST_SPEED,
    arm_deg: int = config.ARM_TEST_DEGREES,
    arm_speed: int = config.ARM_TEST_SPEED,
    pause_s: float = 0.7,
    client: RPiClient | None = None,
) -> dict:
    """Forward for *drive_s*, backward for *drive_s*, then arm up *arm_deg* and back down.
    This MOVES the robot. Returns encoder positions after each step."""
    if not 0 < drive_s <= 3:
        raise ValueError("drive_s must be within 0..3 s")
    if not config.MOTOR_MIN_SPEED <= drive_speed <= config.MOTOR_MAX_SPEED:
        raise ValueError(f"drive speed must be {config.MOTOR_MIN_SPEED}..{config.MOTOR_MAX_SPEED}")
    if not 0 < arm_deg <= 90:
        raise ValueError("arm degrees must be 1..90")
    if not config.ARM_SPEED_MIN <= arm_speed <= config.ARM_SPEED_MAX:
        raise ValueError(f"arm speed must be {config.ARM_SPEED_MIN}..{config.ARM_SPEED_MAX}")
    params = {
        "left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL, "arm": config.PORT_ARM,
        "lsign": config.LEFT_WHEEL_SIGN_FORWARD, "rsign": config.RIGHT_WHEEL_SIGN_FORWARD,
        "drive_s": drive_s, "drive_speed": drive_speed, "pause_s": pause_s,
        "arm_deg": arm_deg, "arm_speed": arm_speed, "arm_sign_down": config.ARM_MOTOR_SIGN_DOWN,
    }
    return (client or get_client()).run_python(_SEQUENCE, params, timeout=60)


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


class LiveMotors:
    """Drive all four motors continuously from the laptop. This MOVES the robot.

    Speeds are in robot terms (-100..100): wheels + = forward, arm + = down,
    gripper + = open. The mounting sign flips are applied here. At speed 0 the
    wheels and gripper go limp and the arm holds where it is; grip_hold (-100..100,
    fixed power, - = close) keeps the gripper squeezing instead of going limp.

        with LiveMotors() as live:
            live.send(left=30, right=30)  # keep calling it, or the Pi's watchdog stops the motors
    """

    def __init__(self, client: RPiClient | None = None, watchdog_s: float = config.PAD_WATCHDOG_S):
        idle = {config.PORT_LEFT_WHEEL: "coast", config.PORT_RIGHT_WHEEL: "coast",
                config.PORT_ARM: "hold", config.PORT_GRIPPER: "coast"}
        params = {"ports": list(idle), "idle": idle, "watchdog_s": watchdog_s}
        self._stdin, self._stdout = (client or get_client()).open_python(_LIVE_MOTORS, params)
        output = []
        for line in self._stdout:  # wait until the HAT is ready (it may load firmware first)
            if line.startswith("__NEIL_RESULT__"):
                break
            output.append(line)
        else:
            raise RuntimeError("Pi live-motor script exited before it was ready:\n" + "".join(output[-20:]))

    def send(self, left: int = 0, right: int = 0, arm: int = 0, grip: int = 0, grip_hold: int = 0) -> None:
        cmd = {
            config.PORT_LEFT_WHEEL: config.LEFT_WHEEL_SIGN_FORWARD * left,
            config.PORT_RIGHT_WHEEL: config.RIGHT_WHEEL_SIGN_FORWARD * right,
            config.PORT_ARM: config.ARM_MOTOR_SIGN_DOWN * arm,
            config.PORT_GRIPPER: config.GRIPPER_MOTOR_SIGN_OPEN * grip,
        }
        if grip_hold:
            cmd["pwm"] = {config.PORT_GRIPPER: config.GRIPPER_MOTOR_SIGN_OPEN * grip_hold / 100}
        self._stdin.write(json.dumps(cmd) + "\n")
        self._stdin.flush()

    def close(self) -> None:
        try:
            self.send()
            self._stdin.channel.shutdown_write()
            self._stdout.channel.recv_exit_status()
        except OSError:
            pass

    def __enter__(self) -> "LiveMotors":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
