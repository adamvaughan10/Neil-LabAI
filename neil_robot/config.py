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

# ── gamepad driving (scripts/gamepad_drive.py) ────────────────────────────────
# The D-pad is on/off, so each direction is one fixed speed (-100..100).
PAD_DRIVE_SPEED = int(os.getenv("PAD_DRIVE_SPEED", "30"))
PAD_TURN_SPEED = int(os.getenv("PAD_TURN_SPEED", "30"))
PAD_ARM_SPEED = int(os.getenv("PAD_ARM_SPEED", "10"))
PAD_GRIPPER_SPEED = int(os.getenv("PAD_GRIPPER_SPEED", "20"))
# After closing, the gripper keeps squeezing at this fixed power (%) so it doesn't
# drop what it holds. lego-robot-mcp carries objects at 40 (GRIPPER_HOLD_PWM 0.4).
PAD_GRIPPER_HOLD = int(os.getenv("PAD_GRIPPER_HOLD", "30"))
PAD_SEND_HZ = 20
# The Pi stops every motor if it hears nothing for this long (laptop froze, SSH dropped).
PAD_WATCHDOG_S = float(os.getenv("PAD_WATCHDOG_S", "0.5"))

# ── camera (Pi Camera v1, OV5647) ─────────────────────────────────────────────
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1296"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "972"))
# The camera is mounted upside down on the robot; the sensor flips it (0 or 180).
CAMERA_ROTATION = int(os.getenv("CAMERA_ROTATION", "180"))
CAMERA_WARMUP_S = float(os.getenv("CAMERA_WARMUP_S", "1.0"))

# 1296x972 is the sensor's full-view binned mode (up to 46 fps).
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1296"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "972"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))

_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = Path(os.getenv("LOGS_DIR", _ROOT / "logs"))
OUTPUT_DIR =Path(os.getenv("OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))
