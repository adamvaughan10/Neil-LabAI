"""
Runs ON THE PI. scripts/gamepad_drive.py sends this file over SSH and starts it,
then writes one JSON command per line to its stdin whenever a button changes:

    {"drive": [left, right]}   wheel motor speeds, -100..100; [0, 0] stops them
    {"arm": degrees}           turn the arm motor by this many degrees, then hold
    {"grip": degrees}          turn the gripper motor by this many degrees, then hold

Speeds and degrees are raw motor values: the laptop applies the mounting sign flips.
If settings["state_hz"] is set, it also prints each motor's measured speed and
angle that many times a second, one line each: state {"A": [speed, angle], ...}
(the dashboard reads these).
When stdin closes (Ctrl-C on the laptop, or SSH drops) every motor stops.
"""
import json
import sys
import threading
import time

from buildhat import Motor, MotorPair

settings = json.loads(sys.argv[1])
wheels = MotorPair(settings["left"], settings["right"])
arm = Motor(settings["arm"])
grip = Motor(settings["grip"])
arm.release = False  # hold the angle after each move instead of going limp
grip.release = False


def report_state(period):
    motors = {settings["left"]: wheels._leftmotor, settings["right"]: wheels._rightmotor,
              settings["arm"]: arm, settings["grip"]: grip}
    while True:
        time.sleep(period)
        try:
            state = {port: m.get()[:2] for port, m in motors.items()}  # [speed, position]
        except Exception as e:  # never let the readout stop the robot
            state = {"error": repr(e)}
        print("state " + json.dumps(state), flush=True)


if settings.get("state_hz"):
    threading.Thread(target=report_state, args=(1 / settings["state_hz"],), daemon=True).start()
print("ready", flush=True)

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
