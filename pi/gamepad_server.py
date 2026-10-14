"""
Runs ON THE PI. scripts/gamepad_drive.py sends this file over SSH and starts it,
then writes one JSON command per line to its stdin whenever a button changes:

    {"drive": [left, right]}   wheel motor speeds, -100..100; [0, 0] stops them
    {"arm": degrees}           turn the arm motor by this many degrees, then hold
    {"grip": degrees}          turn the gripper motor by this many degrees, then hold
    {"wheel_deg": [left, right]}  turn each wheel by this many degrees, like the gripper
                               (scripts/gamepad_drive.py --wheels angle). The steps add up to a
                               target angle per wheel; each move turns a wheel from where it
                               really is to that target, both wheels starting together.

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
left.release = right.release = False  # degree moves: no 0.2 s pause and coast after each step
port_of = {left: settings["left"], right: settings["right"], arm: settings["arm"], grip: settings["grip"]}
print_lock = threading.Lock()


def emit(kind, obj):
    with print_lock:  # one whole line at a time: two threads print
        sys.stdout.write(kind + " " + json.dumps(obj) + "\n")
        sys.stdout.flush()


def call(motor, name, blocking=False, **args):
    """Make a Build HAT call and report it (as it starts, for a blocking move)."""
    emit("hat", {"t": time.time(), "port": port_of[motor], "call": name, **args})
    if name == "start":
        motor.start(args["speed"])
    elif name == "stop":
        motor.stop()
    else:
        motor.run_for_degrees(args["degrees"], speed=args["speed"], blocking=blocking)


last_dir = {left: 0, right: 0}  # direction each wheel last turned: -1, +1, or 0 = never
running = {left: 0, right: 0}  # speed each wheel was last set to
delayed = None  # (wheel, speed, when) waiting for the other wheel to reverse
wheel_target = {}  # --wheels angle: encoder angle each wheel is being turned to (set at startup)
pending_lock = threading.Lock()
CATCH_UP = 3
wake = threading.Event()


def wheel_mover():
    """Turns the wheels toward their target angles, both wheels starting each move
    together (like MotorPair.run_for_degrees). Each move goes from where the wheel
    really is to its target, not just the newest step: on the floor a short move
    falls a few degrees short, and adding up those shortfalls left the wheels at a
    third of the distance asked for. After the last step it tries CATCH_UP more times."""
    while True:
        wake.wait()
        wake.clear()
        tries = 0
        while tries < CATCH_UP or wake.is_set():
            if wake.is_set():
                wake.clear()
                tries = 0
            with pending_lock:
                goals = dict(wheel_target)
            moves = {w: round(goals[w] - w.get_position()) for w in goals}
            moves = {w: d for w, d in moves.items() if abs(d) >= 2}
            if not moves:
                break
            tries += 1
            threads = [threading.Thread(target=call, args=(w, "run_for_degrees"),
                                        kwargs={"blocking": True, "degrees": d, "speed": settings["wheel_speed"]})
                       for w, d in moves.items()]
            for th in threads:
                th.start()
            for th in threads:
                th.join()


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
emit("ready", {"arm": arm.get_position(), "grip": grip.get_position(),
               "left": left.get_position(), "right": right.get_position()})
wheel_target.update({left: left.get_position(), right: right.get_position()})
threading.Thread(target=wheel_mover, daemon=True).start()
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
    if "wheel_deg" in cmd:
        with pending_lock:
            for wheel, degrees in zip((left, right), cmd["wheel_deg"]):
                wheel_target[wheel] += degrees
        wake.set()
    if "arm" in cmd:
        call(arm, "run_for_degrees", degrees=cmd["arm"], speed=settings["arm_speed"])
    if "grip" in cmd:
        call(grip, "run_for_degrees", degrees=cmd["grip"], speed=settings["grip_speed"])

call(left, "stop")
call(right, "stop")
