"""
Live motor state from the Build HAT. READ-ONLY: nothing here powers or moves a motor.

    with MotorStateStream() as motors:
        state = motors.latest()      # MotorState(ts=..., seq=..., motors={...}) or None

A small program runs on the Pi for as long as the stream is open. It opens each
motor port, lets the HAT stream that motor's speed / position / absolute
position continuously, and prints all four motors as one JSON line about 50
times a second. The laptop stamps each line on arrival with its high-resolution
clock, so motor state lines up with the camera frames.

Only one program can use the Build HAT at a time, so motor commands
(hardware.py) can't run while this stream is open.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

from neil_robot import clock, config
from neil_robot.rpi_client import RPiClient

log = logging.getLogger(__name__)

ROLES = {
    config.PORT_LEFT_WHEEL: "left_wheel",
    config.PORT_RIGHT_WHEEL: "right_wheel",
    config.PORT_GRIPPER: "gripper",
    config.PORT_ARM: "arm",
}

# Runs on the Pi. Creating Motor() only selects the HAT's sensor mode and sets
# limits; it sends no drive command. Each port is read in its own thread
# because Motor.get() waits for that port's next sensor update.
_MOTOR_STREAMER = r"""
import json, sys, threading, time
from buildhat import Motor

PORTS = sys.argv[1]
RATE_HZ = float(sys.argv[2])
latest = {p: None for p in PORTS}
errors = {}

def reader(port, m):
    while True:
        try:
            d = m.get()
            latest[port] = {"speed": d[0], "pos": d[1], "apos": d[2] if len(d) > 2 else None,
                            "t": time.time()}
        except Exception as e:
            errors[port] = repr(e)
            time.sleep(0.1)

# Open the ports one at a time: the first Motor() also connects to the HAT,
# and doing that from several threads at once races the connection.
for p in PORTS:
    try:
        m = Motor(p)
    except Exception as e:
        errors[p] = repr(e)
        continue
    threading.Thread(target=reader, args=(p, m), daemon=True).start()

period = 1.0 / RATE_HZ
seq = 0
next_t = time.monotonic()
while True:
    print(json.dumps({"seq": seq, "t": time.time(), "motors": latest, "errors": errors}), flush=True)
    seq += 1
    next_t += period
    time.sleep(max(0.0, next_t - time.monotonic()))
"""

_PI_STREAMER_PATH = "/tmp/neil_motor_streamer.py"


@dataclass(frozen=True)
class MotorState:
    ts: float        # laptop clock.now() when the reading arrived, minus MOTOR_STREAM_LATENCY_S
    pi_t: float      # the Pi's own clock when the reading was printed
    seq: int         # reading counter on the Pi
    motors: dict     # port -> {"speed", "pos", "apos", "t"} or None
    errors: dict     # port -> error text, for ports that failed

    def as_step(self, t: float) -> dict:
        """The reading as one recorder step entry: named by role, with its age at time *t*."""
        out = {"seq": self.seq, "ts": round(self.ts, 6), "age_ms": round((t - self.ts) * 1000, 2)}
        for port, role in ROLES.items():
            m = self.motors.get(port)
            out[role] = None if m is None else {
                "port": port, "pos_deg": m["pos"], "abs_pos_deg": m["apos"], "speed": m["speed"]}
        if self.errors:
            out["errors"] = self.errors
        return out


class MotorStateStream:
    def __init__(self, rate_hz: float = config.MOTOR_STREAM_HZ, ports: str = "".join(config.PORTS)):
        self.rate_hz = rate_hz
        self.ports = ports
        self._client = RPiClient()
        self._channel = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest: MotorState | None = None
        self.error: Exception | None = None
        self.count = 0

    def start(self, wait_s: float = 30) -> "MotorStateStream":
        """Start the Pi-side reader; returns once the first reading with every motor arrives.
        The first connection to the HAT after power-up can take ~10 s (firmware load)."""
        ssh = self._client.connect()
        self._client.run_shell(f"pkill -f {_PI_STREAMER_PATH}; sleep 0.3", timeout=10)
        with ssh.open_sftp() as sftp, sftp.open(_PI_STREAMER_PATH, "w") as f:
            f.write(_MOTOR_STREAMER)
        # A pty ties the streamer's life to this channel: closing it hangs the streamer up.
        self._channel = ssh.get_transport().open_session()
        self._channel.get_pty()
        self._channel.exec_command(f"python3 {_PI_STREAMER_PATH} {self.ports} {self.rate_hz}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._read, name="motors", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            s = self._latest
            if s and all(s.motors.get(p) or p in s.errors for p in self.ports):
                return self
            if self.error:
                break
            time.sleep(0.05)
        self.stop()
        raise RuntimeError(f"motor stream: no complete reading within {wait_s:g} s"
                           + (f" ({self.error})" if self.error else ""))

    def check_ready(self) -> None:
        """Raise if any port failed to open, e.g. "HAT not found" because another
        program (a gamepad driver, a motor test) has the Build HAT open."""
        s = self._latest
        if s and s.errors:
            raise RuntimeError("motors unavailable: " + ", ".join(f"{p}: {e}" for p, e in sorted(s.errors.items())))

    def stop(self) -> None:
        self._stop.set()
        if self._channel:
            self._channel.close()
            self._channel = None
        try:
            self._client.run_shell(f"pkill -f {_PI_STREAMER_PATH}", timeout=10)
        except Exception:  # noqa: BLE001
            pass
        if self._thread:
            self._thread.join(timeout=3)
        self._client.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def latest(self) -> MotorState | None:
        return self._latest

    def _read(self) -> None:
        buf = b""
        try:
            while not self._stop.is_set():
                data = self._channel.recv(65536)
                if not data:
                    raise RuntimeError("motor streamer exited")
                arrived = clock.now() - config.MOTOR_STREAM_LATENCY_S
                buf += data
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    line = line.strip()
                    if not line.startswith(b"{"):
                        if line:
                            log.info("motor streamer: %s", line.decode(errors="replace"))
                        continue
                    msg = json.loads(line)
                    self.count += 1
                    self._latest = MotorState(arrived, msg["t"], msg["seq"], msg["motors"], msg["errors"])
        except Exception as exc:  # noqa: BLE001
            if not self._stop.is_set():
                self.error = exc
                log.warning("motor stream stopped: %s", exc)
