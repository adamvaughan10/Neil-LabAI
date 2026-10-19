"""Settings for talking to the robot. Every value can be overridden with an env var."""
import os
from pathlib import Path

# ── connection ────────────────────────────────────────────────────────────────
RPI_HOST = os.getenv("RPI_HOST", "132.68.34.107")
RPI_USER = os.getenv("RPI_USER", "rpi")
RPI_SSH_KEY = os.getenv("RPI_SSH_KEY") or None  # None: use ~/.ssh keys / agent
SSH_CONNECT_TIMEOUT = float(os.getenv("SSH_CONNECT_TIMEOUT", "10"))

# ── Build HAT wiring ──────────────────────────────────────────────────────────
PORTS = ("A", "B", "C", "D")
PORT_LEFT_WHEEL = os.getenv("PORT_LEFT_WHEEL", "A")
PORT_RIGHT_WHEEL = os.getenv("PORT_RIGHT_WHEEL", "B")
PORT_GRIPPER = os.getenv("PORT_GRIPPER", "C")
PORT_ARM = os.getenv("PORT_ARM", "D")

# ── motor test ────────────────────────────────────────────────────────────────
# Small and slow on purpose: the arm and gripper have mechanical stops.
MOTOR_TEST_DEGREES = int(os.getenv("MOTOR_TEST_DEGREES", "30"))
MOTOR_TEST_SPEED = int(os.getenv("MOTOR_TEST_SPEED", "20"))
MOTOR_MAX_DEGREES = 360
MOTOR_MIN_SPEED, MOTOR_MAX_SPEED = 15, 60

# ── wheels (ports A, B) ───────────────────────────────────────────────────────
# As in lego-robot-mcp: the left motor is mounted reversed, so forward is
# MotorPair(A, B).run_for_seconds(t, -speed, +speed).
LEFT_WHEEL_SIGN_FORWARD = -1
RIGHT_WHEEL_SIGN_FORWARD = 1
DRIVE_TEST_SPEED = int(os.getenv("DRIVE_TEST_SPEED", "40"))
DRIVE_TEST_SECONDS = float(os.getenv("DRIVE_TEST_SECONDS", "0.5"))

# ── arm (port D) ──────────────────────────────────────────────────────────────
# As in lego-robot-mcp: the arm motor is mounted reversed, so a positive motor
# turn raises the arm, and the arm runs slower than the other motors (5..15).
ARM_MOTOR_SIGN_DOWN = -1
ARM_SPEED_MIN, ARM_SPEED_MAX = 5, 15
ARM_TEST_DEGREES = int(os.getenv("ARM_TEST_DEGREES", "30"))
ARM_TEST_SPEED = int(os.getenv("ARM_TEST_SPEED", "10"))

# ── gripper (port C) ──────────────────────────────────────────────────────────
# As in lego-robot-mcp (control_gripper): a negative motor turn opens the gripper.
GRIPPER_MOTOR_SIGN_OPEN = -1

# ── camera (Pi Camera v1, OV5647) ─────────────────────────────────────────────
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1296"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "972"))
# Fixed 180° flip of the Pi camera, done on the sensor. It is the same for every
# frame and never changes while running. 0 shows the image exactly as mounted.
# (The external camera has its own setting, EXTERNAL_CAMERA_ROTATION, left at 0.)
CAMERA_ROTATION = int(os.getenv("CAMERA_ROTATION", "180"))
CAMERA_WARMUP_S = float(os.getenv("CAMERA_WARMUP_S", "1.0"))

# 1296x972 is the sensor's full-view binned mode (up to 46 fps).
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1296"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "972"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))

# ── live streams ──────────────────────────────────────────────────────────────
# Pi camera: an MJPEG server started on the Pi over SSH, read over HTTP.
# Smaller than recordings so both streams fit comfortably on the Wi-Fi.
PI_STREAM_PORT = int(os.getenv("PI_STREAM_PORT", "8765"))
PI_STREAM_WIDTH = int(os.getenv("PI_STREAM_WIDTH", "640"))
PI_STREAM_HEIGHT = int(os.getenv("PI_STREAM_HEIGHT", "480"))
PI_STREAM_FPS = int(os.getenv("PI_STREAM_FPS", "30"))
# External camera: a phone IP-camera app serving MJPEG (plain http, not https).
EXTERNAL_CAMERA_URL = os.getenv("EXTERNAL_CAMERA_URL", "http://132.68.34.85:8080/stream.mjpg")
EXTERNAL_CAMERA_ROTATION = int(os.getenv("EXTERNAL_CAMERA_ROTATION", "0"))  # clockwise: 0/90/180/270
# Capture-to-arrival delay of each camera, subtracted from frame timestamps so frames
# taken at the same moment get the same timestamp. 0 until calibrated.
PI_CAMERA_LATENCY_S = float(os.getenv("PI_CAMERA_LATENCY_S", "0"))
EXTERNAL_CAMERA_LATENCY_S = float(os.getenv("EXTERNAL_CAMERA_LATENCY_S", "0"))
# Motor state stream (read-only): readings per second sent from the Pi, and the
# Pi-to-laptop delay subtracted from their timestamps (SSH on the LAN: ~10 ms).
MOTOR_STREAM_HZ = float(os.getenv("MOTOR_STREAM_HZ", "50"))
MOTOR_STREAM_LATENCY_S = float(os.getenv("MOTOR_STREAM_LATENCY_S", "0"))
# Synced recording rate. 15 fps is the highest where both cameras deliver a new frame
# on (nearly) every step: the external camera tops out around 26 fps, with jitter.
RECORD_FPS = float(os.getenv("RECORD_FPS", "15"))
STREAM_CONNECT_TIMEOUT = float(os.getenv("STREAM_CONNECT_TIMEOUT", "10"))

_ROOT =Path(__file__).resolve().parent.parent
LOGS_DIR = Path(os.getenv("LOGS_DIR", _ROOT / "logs"))
OUTPUT_DIR =Path(os.getenv("OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))
