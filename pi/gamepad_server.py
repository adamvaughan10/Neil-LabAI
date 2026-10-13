"""
Runs ON THE PI. scripts/gamepad_drive.py sends this file over SSH and starts it,
then writes one JSON command per line to its stdin whenever a button changes:

    {"drive": [left, right]}   wheel motor speeds, -100..100; [0, 0] stops them
    {"arm": degrees}           turn the arm motor by this many degrees, then hold
    {"grip": degrees}          turn the gripper motor by this many degrees, then hold

Speeds and degrees are raw motor values: the laptop applies the mounting sign flips.
When stdin closes (Ctrl-C on the laptop, or SSH drops) every motor stops.
"""
import json
import sys

from buildhat import Motor, MotorPair

settings = json.loads(sys.argv[1])
wheels = MotorPair(settings["left"], settings["right"])
arm = Motor(settings["arm"])
grip = Motor(settings["grip"])
arm.release = False  # hold the angle after each move instead of going limp
grip.release = False
# Starting encoder angles, so the laptop can track the absolute target angle.
print("ready " + json.dumps({"arm": arm.get_position(), "grip": grip.get_position()}), flush=True)

for line in iter(sys.stdin.readline, ""):
    cmd = json.loads(line)
    if "drive" in cmd:
        left, right = cmd["drive"]
        if left or right:
            wheels.start(left, right)
        else:
            wheels.stop()
    if "arm" in cmd:
        arm.run_for_degrees(cmd["arm"], speed=settings["arm_speed"], blocking=False)
    if "grip" in cmd:
        grip.run_for_degrees(cmd["grip"], speed=settings["grip_speed"], blocking=False)

wheels.stop()
