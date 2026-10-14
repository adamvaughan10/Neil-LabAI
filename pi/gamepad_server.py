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
Every Build HAT call it makes is also printed as it happens, one line each, e.g.
    hat {"t": 1760356000.81, "port": "A", "call": "start", "speed": -30}
    hat {"t": ..., "port": "D", "call": "run_for_degrees", "degrees": 26, "speed": 25}
("stop" has neither speed nor degrees). The recorder saves these as "hat_commands".
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
port_of = {left: settings["left"], right: settings["right"], arm: settings["arm"], grip: settings["grip"]}
print_lock = threading.Lock()


def emit(kind, obj):
    with print_lock:  # one whole line at a time: two threads print
        sys.stdout.write(kind + " " + json.dumps(obj) + "\n")
        sys.stdout.flush()


def call(motor, name, **args):
    """Make a Build HAT call and report it."""
    if name == "start":
        motor.start(args["speed"])
    elif name == "stop":
        motor.stop()
    else:
        motor.run_for_degrees(args["degrees"], speed=args["speed"], blocking=False)
    emit("hat", {"t": time.time(), "port": port_of[motor], "call": name, **args})


last_dir = {left: 0, right: 0}
running = {left: 0, right: 0}  # speed each wheel was last set to  # direction each wheel last turned: -1, +1, or 0 = never
delayed = None  # (wheel, speed, when) waiting for the other wheel to reverse


def set_speed(wheel, speed):
    if speed == running[wheel]:
        return  # already at that speed: no Build HAT call
    running[wheel] = speed
    if speed:
        call(wheel, "start", speed=speed)
        last_dir[wheel] = 1 if speed > 0 else -1
    else:
        call(wheel, "stop")


def drive(speeds):
    global delayed
    if delayed:
        wheel, speed, when = delayed
        if speeds[wheel] * speed > 0:
            # Still waiting for the other wheel to reverse (a ramping laptop sends a new
            # speed many times a second): keep waiting, with the newest speed.
            delayed = (wheel, speeds[wheel], when)
            for other, s in speeds.items():
                if other is not wheel:
                    set_speed(other, s)
            return
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
        emit("state", state)


# Starting encoder angles, so the laptop can track the absolute target angle.
emit("ready", {"arm": arm.get_position(), "grip": grip.get_position()})
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
        call(arm, "run_for_degrees", degrees=cmd["arm"], speed=settings["arm_speed"])
    if "grip" in cmd:
        call(grip, "run_for_degrees", degrees=cmd["grip"], speed=settings["grip_speed"])

call(left, "stop")
call(right, "stop")
