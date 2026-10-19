"""Neil motor + camera bridge. Runs on the Raspberry Pi as ONE long process.

Start it from the laptop (neil_io.py does this for you):
    ssh rpi@rpi.local python3 -u pi_bridge.py

stdin, one JSON line per command, in the same units and signs as the team's
recorder ("action" in steps.jsonl):
    {"left": 30, "right": 30, "arm_pos": -20, "grip_pos": -60}
      left/right: wheel speed -100..100, + = forward
      arm_pos:    arm target angle in degrees (recorded range about -20..8)
      grip_pos:   gripper target angle in degrees (recorded range about -74..2)
    arm_pos and grip_pos may be left out: the motor then keeps its last target.
stdout, one JSON line per command, in the same signs (= "state" in training):
    {"left_speed": .., "right_speed": .., "arm_pos": .., "grip_pos": .., "t": ..}

A control thread moves the arm and gripper to their targets 25 times a second.
It also serves the front camera as MJPEG on port 8765, like Neil's MCP server.
A watchdog stops the wheels if no command arrives for 0.5 s; arm and gripper hold.

STARTER CODE, NOT TESTED ON NEIL. Check every sign with the robot lifted off the floor.
"""
import io
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from buildhat import Motor

# Signs measured in the team's recordings (Test_1, 2026-10-14): the recorded action
# and these readings agree when the left wheel, arm and gripper are flipped.
LEFT_SIGN, RIGHT_SIGN, ARM_SIGN, GRIP_SIGN = -1, 1, -1, -1
CAM_PORT, CAM_W, CAM_H = 8765, 640, 480
WATCHDOG_S = 0.5
# Position control for arm and gripper: speed = GAIN * error, at most MAX_SPEED
# (the team's controller moved them at speed 25). Targets are clamped to a little
# more than the recorded range, so a bad model output cannot force the arm too far.
GAIN, MAX_SPEED, DEADBAND = 1.5, 25, 2
ARM_RANGE, GRIP_RANGE = (-25, 10), (-80, 5)

left, right, grip, arm = Motor("A"), Motor("B"), Motor("C"), Motor("D")
last_cmd_t = time.time()
lock = threading.Lock()
# Targets in the recorder's signs. Start by holding the current position.
target = {"arm": ARM_SIGN * arm.get_position(), "grip": GRIP_SIGN * grip.get_position()}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def apply(cmd):
    left.start(int(LEFT_SIGN * clamp(cmd.get("left", 0), -100, 100)))
    right.start(int(RIGHT_SIGN * clamp(cmd.get("right", 0), -100, 100)))
    if cmd.get("arm_pos") is not None:
        target["arm"] = clamp(cmd["arm_pos"], *ARM_RANGE)
    if cmd.get("grip_pos") is not None:
        target["grip"] = clamp(cmd["grip_pos"], *GRIP_RANGE)


def drive_to(motor, sign, goal):
    # start(0) keeps a PID loop at zero speed, so the arm holds against gravity.
    error = sign * goal - motor.get_position()
    speed = 0 if abs(error) <= DEADBAND else clamp(GAIN * error, -MAX_SPEED, MAX_SPEED)
    motor.start(int(speed))


def position_loop():
    while True:
        with lock:
            drive_to(arm, ARM_SIGN, target["arm"])
            drive_to(grip, GRIP_SIGN, target["grip"])
        time.sleep(0.04)


def stop_wheels():
    for m in (left, right):
        m.stop()


def watchdog():
    while True:
        time.sleep(0.1)
        with lock:
            if time.time() - last_cmd_t > WATCHDOG_S:
                stop_wheels()


def start_camera():
    from libcamera import Transform
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput

    class Buf(io.BufferedIOBase):
        def __init__(self):
            self.frame, self.cond = b"", threading.Condition()

        def write(self, b):
            with self.cond:
                self.frame = bytes(b)
                self.cond.notify_all()
            return len(b)

    buf = Buf()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            try:
                while True:
                    with buf.cond:
                        buf.cond.wait()
                        f = buf.frame
                    self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(f)).encode() + b"\r\n\r\n" + f + b"\r\n")
            except Exception:
                pass

        def log_message(self, *a):
            pass

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (CAM_W, CAM_H), "format": "RGB888"},
        transform=Transform(hflip=True, vflip=True),  # same as Neil's MCP server
    ))
    cam.start_recording(MJPEGEncoder(), FileOutput(buf))
    threading.Thread(target=HTTPServer(("", CAM_PORT), Handler).serve_forever, daemon=True).start()


def main():
    global last_cmd_t
    start_camera()
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=position_loop, daemon=True).start()
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        cmd = json.loads(line)
        with lock:
            last_cmd_t = time.time()
            apply(cmd)
        state = {
            "left_speed": LEFT_SIGN * left.get_speed(),
            "right_speed": RIGHT_SIGN * right.get_speed(),
            "arm_pos": ARM_SIGN * arm.get_position(),
            "grip_pos": GRIP_SIGN * grip.get_position(),
            "t": time.time(),
        }
        print(json.dumps(state), flush=True)
    stop_wheels()


if __name__ == "__main__":
    main()
