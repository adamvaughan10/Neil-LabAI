"""
Runs ON THE PI. scripts/gamepad_drive.py sends this file over SSH and starts it,
then writes one JSON command per line to its stdin whenever a button changes:

    {"drive": [left, right]}   wheel motor speeds, -100..100; [0, 0] stops them
    {"arm": degrees}           turn the arm motor by this many degrees, then hold
    {"grip": degrees}          turn the gripper motor by this many degrees, then hold

Speeds and degrees are raw motor values: the laptop applies the mounting sign flips.
When only one wheel has to reverse (e.g. forward -> turn), the other wheel stops and
waits settings["reverse_delay"] seconds, so it doesn't push the robot while the
reversing wheel takes up its gear slack.
When stdin closes (Ctrl-C on the laptop, or SSH drops) every motor stops.
"""
import json
import os
import select
import sys
import time

from buildhat import Motor

settings = json.loads(sys.argv[1])
left = Motor(settings["left"])
right = Motor(settings["right"])
arm = Motor(settings["arm"])
grip = Motor(settings["grip"])
arm.release = False  # hold the angle after each move instead of going limp
grip.release = False
running = {left: 0, right: 0}  # speed each wheel is currently running at
delayed = None  # (wheel, speed, when) waiting for the other wheel to reverse


def set_speed(wheel, speed):
    if speed:
        wheel.start(speed)
    else:
        wheel.stop()
    running[wheel] = speed


def drive(speeds):
    global delayed
    delayed = None
    reversing = [w for w, s in speeds.items() if s * running[w] < 0]
    for wheel, speed in speeds.items():
        if len(reversing) == 1 and wheel not in reversing and speed:
            set_speed(wheel, 0)
            delayed = (wheel, speed, time.monotonic() + settings["reverse_delay"])
        else:
            set_speed(wheel, speed)


# Starting encoder angles, so the laptop can track the absolute target angle.
print("ready " + json.dumps({"arm": arm.get_position(), "grip": grip.get_position()}), flush=True)

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
