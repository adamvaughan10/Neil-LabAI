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

Commands for the delta model (models/handoff_pick_cup_pos2), see its README:
    {"left_deg": 40, "right_deg": 38, "seq": 7, "arm_abs": 12, "grip_abs": -70}
      left_deg/right_deg: degrees the wheel should still turn from where it is now,
          + = forward. Like run_for_degrees(deg, speed=30), but each command replaces
          the previous move instead of queueing after it (buildhat queues non-blocking
          run_for_degrees calls). 0 stops the wheel where it is. A command with the same
          "seq" as the last one does not move the target again.
          Any command with "left"/"right" speeds, or none of these keys, cancels the move.
      arm_abs/grip_abs: arm and gripper targets as raw abs_pos_deg (the motor's own
          fixed zero, which survives Build HAT restarts, unlike pos_deg).
    and stdout also carries left_deg, right_deg (wheel encoder angles, same signs)
    and arm_abs, grip_abs (raw abs_pos_deg: pos_deg + the offset measured at start).

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
# Wheel speed cap. Every recorded wheel action is -30, 0 or +30, so 30 loses nothing.
MAX_WHEEL = 30
# Position control for arm and gripper: speed = GAIN * error, at most MAX_SPEED
# (the team's controller moved them at speed 25). Targets are clamped to a little
# more than the recorded range, so a bad model output cannot force the arm too far.
GAIN, MAX_SPEED, DEADBAND = 1.5, 25, 2
ARM_RANGE, GRIP_RANGE = (-25, 10), (-80, 5)
# Delta model: abs_pos_deg target limits, a little wider than its training data
# (arm 2..48, gripper -12..-98), and the wheel position controller.
ARM_ABS_RANGE, GRIP_ABS_RANGE = (0, 50), (-100, -10)
WHEEL_GAIN, WHEEL_DEADBAND = 2.0, 2

left, right, grip, arm = Motor("A"), Motor("B"), Motor("C"), Motor("D")
last_cmd_t = time.time()
lock = threading.Lock()
# Targets in the recorder's signs. Start by holding the current position.
target = {"arm": ARM_SIGN * arm.get_position(), "grip": GRIP_SIGN * grip.get_position()}
# Wheel position targets (raw pos_deg) while the delta model drives; None = speed control.
wheel_target = {"left": None, "right": None}
last_seq = None
wheel_cap = MAX_WHEEL  # a command's "wheel_cap" lowers the wheel speed of left_deg/right_deg moves


def abs_offset(m):
    """abs_pos_deg - pos_deg in this Build HAT session (median of 5 readings, whole degrees)."""
    offs = []
    for _ in range(5):
        offs.append(m.get_aposition() - m.get_position())
        time.sleep(0.02)
    return round(sorted(offs)[2])


ARM_OFF, GRIP_OFF = abs_offset(arm), abs_offset(grip)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def apply(cmd):
    global last_seq, wheel_cap
    if cmd.get("wheel_cap") is not None:
        wheel_cap = clamp(cmd["wheel_cap"], 0, MAX_WHEEL)
    new_move = cmd.get("seq") is None or cmd["seq"] != last_seq
    for name, m, sign in (("left", left, LEFT_SIGN), ("right", right, RIGHT_SIGN)):
        if cmd.get(name + "_deg") is not None:
            if new_move:
                wheel_target[name] = m.get_position() + sign * cmd[name + "_deg"]
        else:
            wheel_target[name] = None
            m.start(int(sign * clamp(cmd.get(name, 0), -MAX_WHEEL, MAX_WHEEL)))
    last_seq = cmd.get("seq")
    if cmd.get("arm_pos") is not None:
        target["arm"] = clamp(cmd["arm_pos"], *ARM_RANGE)
    if cmd.get("grip_pos") is not None:
        target["grip"] = clamp(cmd["grip_pos"], *GRIP_RANGE)
    # abs targets -> the pos_deg-based targets the position loop uses (recorder signs)
    if cmd.get("arm_abs") is not None:
        target["arm"] = ARM_SIGN * (clamp(cmd["arm_abs"], *ARM_ABS_RANGE) - ARM_OFF)
    if cmd.get("grip_abs") is not None:
        target["grip"] = GRIP_SIGN * (clamp(cmd["grip_abs"], *GRIP_ABS_RANGE) - GRIP_OFF)


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
            for name, m in (("left", left), ("right", right)):
                if wheel_target[name] is not None:
                    error = wheel_target[name] - m.get_position()
                    m.start(int(0 if abs(error) <= WHEEL_DEADBAND
                                else clamp(WHEEL_GAIN * error, -wheel_cap, wheel_cap)))
        time.sleep(0.04)


def stop_wheels():
    wheel_target["left"] = wheel_target["right"] = None
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
            "left_deg": LEFT_SIGN * left.get_position(),
            "right_deg": RIGHT_SIGN * right.get_position(),
            "arm_abs": arm.get_position() + ARM_OFF,
            "grip_abs": grip.get_position() + GRIP_OFF,
            "t": time.time(),
        }
        print(json.dumps(state), flush=True)
    stop_wheels()


if __name__ == "__main__":
    main()
