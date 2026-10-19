"""
Runs ON THE PI. scripts/replay_session.py sends this file over SSH and starts it.

It prints `ready {...}` with every motor's [speed, angle, absolute angle], then reads
ONE line from stdin: the recorded Build HAT calls, as a JSON list of
    {"t": seconds from the start, "port": "A", "call": "start" | "stop" | "run_for_degrees",
     "speed": ..., "degrees": ...}
and makes each call at its time, timed on the Pi so Wi-Fi jitter doesn't shift them.
Every call made is printed as `hat {...}` with the time it really ran, and every
motor's state is printed settings["state_hz"] times a second as
    state {"t": seconds from the start, "A": [speed, angle, absolute angle], ...}
After the last call it keeps reporting for settings["tail"] seconds, stops the
wheels and prints `done {}`. If stdin closes early (Ctrl-C on the laptop, or SSH
drops) it stops at once, wheels stopped.
"""
import json
import sys
import threading
import time

from buildhat import Motor

settings = json.loads(sys.argv[1])
motors = {port: Motor(port) for port in settings["ports"]}
for port in settings["hold"]:  # arm and gripper hold their angle after each move
    motors[port].release = False
print_lock = threading.Lock()


def emit(kind, obj):
    with print_lock:  # one whole line at a time: two threads print
        sys.stdout.write(kind + " " + json.dumps(obj) + "\n")
        sys.stdout.flush()


emit("ready", {port: m.get() for port, m in motors.items()})
calls = json.loads(sys.stdin.readline())
t0 = time.monotonic()
done = threading.Event()


def report_state(period):
    while not done.is_set():
        time.sleep(period)
        try:
            state = {port: m.get() for port, m in motors.items()}
        except Exception as e:  # never let the readout stop the replay
            state = {"error": repr(e)}
        emit("state", {"t": round(time.monotonic() - t0, 4), **state})


def watch_stdin():
    sys.stdin.read()  # returns when the laptop closes stdin
    done.set()


threading.Thread(target=report_state, args=(1 / settings["state_hz"],), daemon=True).start()
threading.Thread(target=watch_stdin, daemon=True).start()

for c in calls:
    if done.wait(max(0.0, c["t"] - (time.monotonic() - t0))):
        break
    m = motors[c["port"]]
    if c["call"] == "start":
        m.start(c["speed"])
    elif c["call"] == "stop":
        m.stop()
    else:
        m.run_for_degrees(c["degrees"], speed=c["speed"], blocking=False)
    emit("hat", {**c, "planned": c["t"], "t": round(time.monotonic() - t0, 4)})
done.wait(settings["tail"])
done.set()
for port in settings["wheels"]:
    motors[port].stop()
emit("done", {})
