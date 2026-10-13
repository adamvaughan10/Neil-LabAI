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

# ── camera (Pi Camera v1, OV5647) ─────────────────────────────────────────────
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1296"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "972"))
CAMERA_WARMUP_S = float(os.getenv("CAMERA_WARMUP_S", "1.0"))

# 1296x972 is the sensor's full-view binned mode (up to 46 fps).
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1296"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "972"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))

_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = Path(os.getenv("LOGS_DIR", _ROOT / "logs"))
OUTPUT_DIR =Path(os.getenv("OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))
