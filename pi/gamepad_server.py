"""
Runs ON THE PI. scripts/gamepad_drive.py sends this file over SSH and starts it,
then writes one JSON command per line to its stdin whenever a button changes:

    {"drive": [left, right]}   wheel motor speeds, -100..100; [0, 0] stops them
    {"arm": degrees}           turn the arm motor by this many degrees, then hold
    {"grip": degrees}          turn the gripper motor by this many degrees, then hold

Speeds and degrees are raw motor values: the laptop applies the mounting sign flips.
When one wheel now turns opposite to the direction it last turned (even if it has
stopped since) and the other wheel doesn't, the other wheel waits
settings["reverse_delay"] seconds while the reversing wheel takes up its gear slack.
E.g. forward, then left: the right wheel waits. Forward then back: no wait.
If settings["state_hz"] is set, it also prints each motor's measured speed and
angle that many times a second, one line each: state {"A": [speed, angle], ...}
(same format as the motor-dashboard and episode-recorder branches).
When stdin closes (Ctrl-C on the laptop, or SSH drops) every motor stops.
"""
import json
import os
import select
import sys
import threading
import time

from buildhat import Motor

settings = json.loads(sys.argv[1])
left = Motor(settings["left"])
right = Motor(settings["right"])
arm = Motor(settings["arm"])
grip = Motor(settings["grip"])
arm.release = False  # hold the angle after each move instead of going limp
grip.release = False
last_dir = {left: 0, right: 0}  # direction each wheel last turned: -1, +1, or 0 = never
delayed = None  # (wheel, speed, when) waiting for the other wheel to reverse


def set_speed(wheel, speed):
    if speed:
        wheel.start(speed)
        last_dir[wheel] = 1 if speed > 0 else -1
    else:
        wheel.stop()


def drive(speeds):
    global delayed
    delayed = None
    reversing = [w for w, s in speeds.items() if s * last_dir[w] < 0]
    for wheel, speed in speeds.items():
        if len(reversing) == 1 and wheel not in reversing and speed:
            set_speed(wheel, 0)
            delayed = (wheel, speed, time.monotonic() + settings["reverse_delay"])
        else:
            set_speed(wheel, speed)


def report_state(period):
    motors = {settings["left"]: left, settings["right"]: right,
              settings["arm"]: arm, settings["grip"]: grip}
    while True:
        time.sleep(period)
        try:
            state = {port: m.get() for port, m in motors.items()}  # [speed, position, absolute position]
        except Exception as e:  # never let the readout stop the robot
            state = {"error": repr(e)}
        print("state " + json.dumps(state), flush=True)


# Starting encoder angles, so the laptop can track the absolute target angle.
print("ready " + json.dumps({"arm": arm.get_position(), "grip": grip.get_position()}), flush=True)
if settings.get("state_hz"):
    threading.Thread(target=report_state, args=(1 / settings["state_hz"],), daemon=True).start()

stdin = os.fdopen(0, "rb", buffering=0)  # unbuffered, so select() sees every waiting line
while True:
    timeout = max(0.0, delayed[2] - time.monotonic()) if delayed else None
    if not select.select([stdin], [], [], timeout)[0]:
        wheel, speed, _ = delayed
        set_speed(wheel, speed)
        delayed = None
        continue
    line = stdin.readline()
    if not line:
        break
    cmd = json.loads(line)
    if "drive" in cmd:
        drive({left: cmd["drive"][0], right: cmd["drive"][1]})
    if "arm" in cmd:
        arm.run_for_degrees(cmd["arm"], speed=settings["arm_speed"], blocking=False)
    if "grip" in cmd:
        grip.run_for_degrees(cmd["grip"], speed=settings["grip_speed"], blocking=False)

left.stop()
right.stop()
