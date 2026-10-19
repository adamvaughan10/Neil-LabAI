"""Laptop side of Neil I/O: the SSH motor bridge, the two cameras, and the dataset format.

Used by record_neil.py (record with a gamepad) and run_policy.py (SmolVLA drives).
STARTER CODE, NOT TESTED ON NEIL.
"""
import json
import os
import subprocess
import threading
import time

import cv2
import numpy as np

PI = os.getenv("NEIL_PI", "rpi@rpi.local")
PI_BRIDGE = os.getenv("NEIL_PI_BRIDGE", "~/pi_bridge.py")
SSH_KEY = os.getenv("NEIL_SSH_KEY")  # e.g. ~/.ssh/id_ed25519_labpi, when ssh does not pick it by itself
FRONT_URL = os.getenv("NEIL_FRONT_URL", "http://rpi.local:8765/")
# Overhead iPhone (SimpleIPCamera app). Not rotated: the team's recorder saves it as the
# phone sends it (1280x720), and we shrink it to 640x360, so live images match the training data.
TOP_URL = os.getenv("NEIL_TOP_URL", "http://132.68.34.44:8080/stream.mjpg")

FPS = 10                          # the team recorded at 10 frames per second
IMG_H, IMG_W = 480, 640          # front (Pi)
TOP_H, TOP_W = 360, 640          # top (iPhone)
STATE_NAMES = ["left_speed", "right_speed", "arm_pos", "grip_pos"]
# Wheel speeds plus arm and gripper TARGET angles, as in the recorder's action.vector.
ACTION_NAMES = ["left", "right", "arm_pos", "grip_pos"]

# The delta model (models/handoff_pick_cup_pos2) instead takes the arm and gripper as
# -(abs_pos_deg - ARM_ABS0) and -(abs_pos_deg - GRIP_ABS0), and returns "wheel degrees still
# to turn" plus arm and gripper targets on that scale. See that model's README.
ARM_ABS0, GRIP_ABS0 = 14, -93
# The angle model (models/pick_cup_angle_182076, no README; worked out from its normaliser
# stats) takes the arm and gripper as -abs_pos_deg, and each wheel as its encoder angle
# since the start of the run (+ = forward); its wheel actions are target angles on that scale.
ABS0 = {"delta": (ARM_ABS0, GRIP_ABS0), "angle": (0, 0)}
MAX_WHEEL_STEP = 120  # angle model: most degrees one command may ask a wheel to turn

# camera1 / camera2 match the camera names in lerobot/smolvla_base, so no rename is needed.
FEATURES = {
    "observation.state": {"dtype": "float32", "shape": (4,), "names": STATE_NAMES},
    "observation.images.camera1": {"dtype": "video", "shape": (IMG_H, IMG_W, 3),
                                   "names": ["height", "width", "channels"]},  # front (Pi)
    "observation.images.camera2": {"dtype": "video", "shape": (TOP_H, TOP_W, 3),
                                   "names": ["height", "width", "channels"]},  # top (iPhone)
    "action": {"dtype": "float32", "shape": (4,), "names": ACTION_NAMES},
}


class Bridge:
    """One SSH process to pi_bridge.py. send() returns the robot state as a dict.
    hold() reads the state without moving: wheels stop, arm and gripper keep their targets."""

    def __init__(self):
        self.p = subprocess.Popen(["ssh", *(["-i", os.path.expanduser(SSH_KEY)] if SSH_KEY else []),
                                   PI, "python3", "-u", PI_BRIDGE],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        hello = json.loads(self.p.stdout.readline())
        assert hello.get("ready"), hello
        time.sleep(1.0)  # let the front camera server start

    def send(self, action):
        return self._write(dict(zip(ACTION_NAMES, map(float, action))))

    def command(self, cmd):
        """Send a pi_bridge.py command dict as it is (e.g. delta_command's)."""
        return self._write(cmd)

    def hold(self):
        return self._write({"left": 0, "right": 0})

    def _write(self, cmd):
        self.p.stdin.write(json.dumps(cmd) + "\n")
        return json.loads(self.p.stdout.readline())

    def stop(self):
        try:
            self.hold()
            self.p.stdin.close()
        finally:
            self.p.terminate()


class Camera:
    """Reads an MJPEG stream in a thread. read() gives the newest RGB frame, resized to (w, h)."""

    def __init__(self, url, w=IMG_W, h=IMG_H):
        self.url, self.size, self.frame = url, (w, h), None
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cap = cv2.VideoCapture(self.url)
        while True:
            ok, f = cap.read()
            if not ok:
                time.sleep(0.5)
                cap = cv2.VideoCapture(self.url)
                continue
            f = cv2.cvtColor(cv2.resize(f, self.size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
            with self.lock:
                self.frame = f

    def read(self):
        while self.frame is None:
            time.sleep(0.05)
        with self.lock:
            return self.frame.copy()


def open_cameras():
    return Camera(FRONT_URL), Camera(TOP_URL, TOP_W, TOP_H)


def state_vector(s, mode="v1", wheel0=(0.0, 0.0)):
    """The model's 4 state values from a pi_bridge.py reading. wheel0: the angle model's wheel
    angles at the start of the run (its wheel state counts from there)."""
    if mode in ABS0:
        za, zg = ABS0[mode]
        wheels = [s["left_speed"], s["right_speed"]] if mode == "delta" else \
            [s["left_deg"] - wheel0[0], s["right_deg"] - wheel0[1]]
        return np.array(wheels + [za - s["arm_abs"], zg - s["grip_abs"]], dtype=np.float32)
    return np.array([s[k] for k in STATE_NAMES], dtype=np.float32)


def delta_command(action, lo, hi, deadband=3.0, mode="delta", wheel_now=None):
    """A delta or angle model action -> the pi_bridge.py command. Clipped to [lo, hi] (the
    training range, per value). delta: the wheel values are degrees still to turn; angle: they
    are target angles, so the move is target - wheel_now (the wheel state values now), at most
    MAX_WHEEL_STEP. Wheel moves under `deadband` degrees count as 0 (stay where it is)."""
    a = np.clip(np.asarray(action[:4], dtype=np.float64), lo, hi)
    moves = a[:2] if mode == "delta" else np.clip(a[:2] - np.asarray(wheel_now, dtype=np.float64),
                                                  -MAX_WHEEL_STEP, MAX_WHEEL_STEP)
    wheels = [0.0 if abs(v) < deadband else round(float(v), 1) for v in moves]
    za, zg = ABS0[mode]
    return {"left_deg": wheels[0], "right_deg": wheels[1],
            "arm_abs": round(za - float(a[2]), 1), "grip_abs": round(zg - float(a[3]), 1)}
